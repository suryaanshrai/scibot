"""
app.agent.orchestrator — LangGraph StateGraph orchestrator for SciBot.

Features
--------
* Short-term memory       — checkpointer + thread_id (multi-turn conversation)
* Long-term memory        — InMemoryStore with (username, "research_notes") namespace
* Human-in-the-loop       — approval_gate node uses interrupt() for expensive tools
* Streaming tokens        — astream() in messages + updates mode
* Time travel             — get_history() / fork_from() via LangGraph checkpoint API
* Durable execution       — automatic with checkpointer (crash-safe)
* Source annotation       — extract_sources parses ToolMessages into SourceRecords
* Relevance filtering     — search_storage chunks below VECTOR_STORE_RELEVANCE_THRESHOLD
                            are kept in state but excluded from the LLM context
* Citation grounding      — run_checker fires on research queries (not data analysis)
* Message summarization   — finalize() condenses messages > MSG_SUMMARIZE_THRESHOLD
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Sequence

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, interrupt

from app.agent.checker import CheckerAgent, CheckResult
from app.agent.researcher import build_researcher_tool
from app.agent.state import (
    AgentState,
    MSG_SUMMARIZE_THRESHOLD,
    SourceRecord,
    VECTOR_STORE_RELEVANCE_THRESHOLD,
)
from app.config.llm_model import get_llm
from app.tools import build_tools
from app.users.config import resolve_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ORCHESTRATOR_SYSTEM = """\
You are SciBot, a scientific AI research assistant. You have access to:
- The user's personal knowledge store (search_storage)
- Scientific literature: arXiv (arxiv_search) and PubMed (pubmed_search)
- Web search (web_search)
- Data loading and structured analysis (get_data, analyze_data)
- A specialized deep-research sub-agent (invoke_researcher) for complex \
  multi-source queries

Citation rules (MANDATORY):
1. ALWAYS cite sources inline as [1], [2], [3] using ONLY the source numbers
   listed in the ## Available Sources section below (when present).
2. Do NOT invent citation numbers that are not in the sources list.
3. If a claim comes from your training knowledge (not retrieved), explicitly
   note "(prior knowledge, not verified from sources)".
4. End every research answer with a ## Sources section listing only the
   sources you actually cited.

Tool selection guidance:
- If an active chat collection is provided in context, treat it as the default
    target for ambiguous follow-up questions such as "what is the paper about?"
    or "summarize this" unless the user explicitly switches collections.
- For simple lookups use retrieval tools directly.
- For short reading-list questions such as "which papers should I read" or
    "papers related to X", prefer direct literature lookup and answer with a
    concise recommendation list instead of delegating to invoke_researcher.
- For questions requiring synthesis across multiple papers, delegate to
  invoke_researcher.
- Use analyze_data only after loading data with get_data.
- Be precise and scientific. Prefer specificity over generality.
"""

SUMMARIZE_PROMPT = """\
The following is the conversation so far (condensed summary may already exist):

Existing summary:
{summary}

New messages to incorporate:
{messages}

Write an updated, concise summary of the entire conversation.
"""

# ---------------------------------------------------------------------------
# Expensive-tool detection
# ---------------------------------------------------------------------------

_ALWAYS_EXPENSIVE = {"get_data", "analyze_data"}


def _is_expensive_call(tool_call: dict) -> bool:
    """Return True when the tool call requires human approval (get_data / analyze_data)."""
    return tool_call.get("name", "") in _ALWAYS_EXPENSIVE


# ---------------------------------------------------------------------------
# Research-tool detection (determines whether checker fires)
# ---------------------------------------------------------------------------

_RESEARCH_TOOLS = {
    "search_storage",
    "web_search",
    "arxiv_search",
    "pubmed_search",
    "invoke_researcher",
}


def _get_turn_tool_names(messages: Sequence[BaseMessage]) -> list[str]:
    """
    Return the names of all tools executed since the most recent HumanMessage.
    Computed directly from the message history — no extra state field required.
    """
    tool_names: list[str] = []
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            break
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "")
            if name:
                tool_names.append(name)
    return tool_names


# ---------------------------------------------------------------------------
# Collection catalog builder
# ---------------------------------------------------------------------------


def _build_collection_catalog(username: str) -> str:
    """
    Build a '## Your Knowledge Collections' block describing all collections
    owned by *username*.  Injected once per turn so the LLM knows which
    knowledge bases are searchable via search_storage.

    Returns empty string on any error (DB unavailable, no collections, etc.).
    """
    try:
        from app.users.collections_db import list_collections, load_collection  # noqa: PLC0415

        summaries = list_collections(username)
        if not summaries:
            return ""
        lines = [
            "## Collection Routing Context",
            "Internal context only. Do not quote or reproduce this catalog verbatim to the user.",
            "Use it only to choose the correct `collection_name` for `search_storage`.",
            "",
        ]
        for summary in summaries:
            cname = summary["collection_name"]
            counts = summary.get("source_counts", {})
            total = sum(counts.values())
            lines.append(f"- {cname} ({total} source{'s' if total != 1 else ''})")
        lines.append("")
        lines.append("When the user asks to list collections, summarize naturally instead of copying this block.")
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        return ""


def _build_active_collection_context(username: str, collection_name: str) -> str:
    """Build a compact context block for the chat's active collection."""
    try:
        from app.users.collections_db import load_collection  # noqa: PLC0415

        data = load_collection(username, collection_name) or {}
        source_labels: list[str] = []
        for paper in (data.get("papers") or [])[:6]:
            title = paper.get("title") or paper.get("source_url") or "paper"
            source_labels.append(str(title))
        for video in (data.get("youtube") or [])[:4]:
            title = video.get("title") or video.get("url") or "youtube"
            source_labels.append(str(title))

        lines = [
            "## Active Chat Collection",
            f"Default collection for this chat: `{collection_name}`.",
            "For ambiguous follow-up questions, call `search_storage` on this collection before answering.",
        ]
        if source_labels:
            lines.append("Known items in this collection:")
            lines.extend(f"- {label}" for label in source_labels)
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Source manifest builder
# ---------------------------------------------------------------------------


def _build_source_manifest(source_records: list[SourceRecord]) -> str:
    """
    Build the "## Available Sources" block injected into the call_model
    system prompt so the LLM knows which [N] IDs it may cite.
    """
    visible = [r for r in source_records if not r.filtered]
    if not visible:
        return ""
    lines = ["## Available Sources"]
    for rec in visible:
        lines.append(
            f"[{rec.ref_id}] {rec.title} ({rec.source_type}) — {rec.url}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Source extractor — parses ToolMessage text into SourceRecord list
# ---------------------------------------------------------------------------

# search_storage block separator (result blocks are joined by double newlines)
_VS_SEP = re.compile(r"\n\n+")
# within a block, metadata is separated from content by a unicode box-drawing line (─ U+2500)
_VS_CONTENT_SEP = re.compile(r"\s*\u2500{3,}\s*\n")
# search_storage field patterns
_VS_SCORE = re.compile(r"Vector score\s*:\s*([\d.]+)", re.IGNORECASE)
_VS_TITLE = re.compile(r"Title\s*:\s*(.+)", re.IGNORECASE)
_VS_URL = re.compile(r"Source URL\s*:\s*(\S+)", re.IGNORECASE)
_VS_STYPE = re.compile(r"Source type\s*:\s*(\S+)", re.IGNORECASE)
# arxiv / pubmed patterns
_AP_ENTRY = re.compile(r"\[(\d+)\]\s+(.+)")
_AP_URL = re.compile(r"URL\s*:\s*(\S+)", re.IGNORECASE)
_AP_SNIPPET = re.compile(r"---\s*\n(.+?)(?=\n\[\d|\Z)", re.DOTALL)
# web_search patterns
_WS_ENTRY = re.compile(r"^(\d+)\.\s+(.+)$", re.MULTILINE)
_WS_URL = re.compile(r"^\s+URL:\s*(\S+)$", re.MULTILINE)
_WS_SNIPPET = re.compile(r"^\s{3}(.+)$", re.MULTILINE)


def _extract_sources_from_tool_messages(
    messages: Sequence[BaseMessage],
    existing_count: int,
) -> list[SourceRecord]:
    """
    Parse the most-recent batch of ToolMessages in *messages* into a list of
    SourceRecord objects.  The ref_id counter starts at existing_count + 1.
    """
    # Collect the trailing run of ToolMessages (the current tool batch)
    tool_msgs: list[ToolMessage] = []
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            tool_msgs.insert(0, msg)
        else:
            break  # stop at the first non-ToolMessage

    records: list[SourceRecord] = []
    counter = existing_count + 1

    for tm in tool_msgs:
        tool_name = getattr(tm, "name", "") or ""
        content = tm.content if isinstance(tm.content, str) else ""

        if tool_name == "search_storage":
            records.extend(_parse_search_storage(content, tool_name, counter))
            counter += len(records) - (counter - existing_count - 1)

        elif tool_name in {"arxiv_search", "pubmed_search"}:
            new = _parse_arxiv_pubmed(content, tool_name, counter)
            records.extend(new)
            counter += len(new)

        elif tool_name == "web_search":
            new = _parse_web_search(content, tool_name, counter)
            records.extend(new)
            counter += len(new)

        elif tool_name == "invoke_researcher":
            # Researcher output already uses the same format as arxiv/pubmed/web
            new = _parse_arxiv_pubmed(content, tool_name, counter)
            if not new:
                new = _parse_web_search(content, tool_name, counter)
            records.extend(new)
            counter += len(new)

        elif tool_name in {"get_data", "analyze_data"}:
            # Treat the alias / file path as a data source reference
            alias_match = re.search(r"alias[:\s]+(\S+)", content, re.IGNORECASE)
            path_match = re.search(r"(?:file|path)[:\s]+(\S+)", content, re.IGNORECASE)
            label = (alias_match or path_match)
            label_str = label.group(1) if label else f"{tool_name} output"
            records.append(SourceRecord(
                ref_id=counter,
                title=label_str,
                url=label_str,
                source_type="data",
                tool_name=tool_name,
                snippet=content[:300],
                relevance_score=1.0,
                filtered=False,
            ))
            counter += 1

    return records


def _parse_search_storage(
    content: str, tool_name: str, start_id: int
) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    ref_id = start_id
    blocks = _VS_SEP.split(content)
    for block in blocks:
        score_m = _VS_SCORE.search(block)
        title_m = _VS_TITLE.search(block)
        url_m = _VS_URL.search(block)
        stype_m = _VS_STYPE.search(block)
        if not (score_m and title_m):
            continue
        score = float(score_m.group(1))
        title = title_m.group(1).strip()
        url = url_m.group(1).strip() if url_m else ""
        stype = stype_m.group(1).strip() if stype_m else "vector_store"
        # Content comes after the unicode box-drawing separator line (─────)
        content_parts = _VS_CONTENT_SEP.split(block, maxsplit=1)
        snippet = content_parts[1].strip()[:300] if len(content_parts) > 1 else ""
        filtered = score < VECTOR_STORE_RELEVANCE_THRESHOLD
        records.append(SourceRecord(
            ref_id=ref_id,
            title=title,
            url=url,
            source_type=stype,
            tool_name=tool_name,
            snippet=snippet,
            relevance_score=score,
            filtered=filtered,
        ))
        ref_id += 1
    return records


def _parse_arxiv_pubmed(
    content: str, tool_name: str, start_id: int
) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    ref_id = start_id
    # Split into chunks by entry header "[N] Title"
    entries = _AP_ENTRY.split(content)
    # entries = [prefix, idx, title, rest, idx, title, rest, ...]
    i = 1
    while i + 2 <= len(entries):
        title = entries[i + 1].strip()
        body = entries[i + 2] if i + 2 < len(entries) else ""
        url_m = _AP_URL.search(body)
        url = url_m.group(1).strip() if url_m else ""
        snippet_m = _AP_SNIPPET.search(body)
        snippet = snippet_m.group(1).strip()[:300] if snippet_m else body[:300]
        records.append(SourceRecord(
            ref_id=ref_id,
            title=title,
            url=url,
            source_type="paper",
            tool_name=tool_name,
            snippet=snippet,
            relevance_score=1.0,
            filtered=False,
        ))
        ref_id += 1
        i += 3
    return records


def _parse_web_search(
    content: str, tool_name: str, start_id: int
) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    ref_id = start_id
    entry_matches = list(_WS_ENTRY.finditer(content))
    for idx, match in enumerate(entry_matches):
        title = match.group(2).strip()
        # Body = text between this entry and the next one
        body_start = match.end()
        body_end = entry_matches[idx + 1].start() if idx + 1 < len(entry_matches) else len(content)
        body = content[body_start:body_end]
        url_m = _WS_URL.search(body)
        url = url_m.group(1).strip() if url_m else ""
        snippets = _WS_SNIPPET.findall(body)
        snippet = " ".join(snippets)[:300]
        records.append(SourceRecord(
            ref_id=ref_id,
            title=title,
            url=url,
            source_type="webpage",
            tool_name=tool_name,
            snippet=snippet,
            relevance_score=1.0,
            filtered=False,
        ))
        ref_id += 1
    return records


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def _recall_memories(
    state: AgentState, config: RunnableConfig, store: InMemoryStore
) -> dict:
    """
    Retrieve relevant notes from the long-term store and prepend them as a
    SystemMessage so the model has cross-session context.
    """
    username = (config.get("configurable") or {}).get("username", "")
    active_collection_name = (config.get("configurable") or {}).get("active_collection_name", "")
    catalog = _build_collection_catalog(username) if username else ""

    if not username or not state["messages"]:
        # Always reset source_records at turn start even when no memories found
        if catalog:
            return {"messages": [SystemMessage(content=catalog)], "source_records": None}
        return {"source_records": None}

    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    if last_human is None:
        return {}

    query = last_human.content if isinstance(last_human.content, str) else ""
    try:
        results = await store.asearch(
            (username, "research_notes"),
            query=query,
            limit=5,
        )
    except Exception:
        if catalog:
            return {"messages": [SystemMessage(content=catalog)], "source_records": None}
        return {}

    memories_text = "\n".join(
        f"- {item.value.get('memory', '')}"
        for item in results
        if item.value.get("memory")
    )

    context_parts: list[str] = []
    if active_collection_name:
        active_context = _build_active_collection_context(username, active_collection_name)
        if active_context:
            context_parts.append(active_context)
    if catalog:
        context_parts.append(catalog)
    if memories_text:
        context_parts.append(f"## Research context from prior sessions:\n{memories_text}")

    if not context_parts:
        return {"source_records": None}

    system_msg = SystemMessage(content="\n\n".join(context_parts))
    # Returning None for source_records triggers _list_reset_reducer to clear
    # the accumulated records from the previous turn.
    return {"messages": [system_msg], "source_records": None}


def _call_model(state: AgentState, llm_with_tools: Any) -> dict:
    """
    Call the LLM with the full message history and an injected system prompt
    that includes the current source manifest (if any).
    """
    messages = state["messages"]
    source_records: list[SourceRecord] = state.get("source_records") or []

    # Build dynamic system prompt
    parts = [ORCHESTRATOR_SYSTEM]
    if state.get("summary"):
        parts.append(f"\n## Conversation Summary (earlier context)\n{state['summary']}")
    manifest = _build_source_manifest(source_records)
    if manifest:
        parts.append(f"\n{manifest}")
    system_content = "\n".join(parts)

    response = llm_with_tools.invoke(
        [SystemMessage(content=system_content)] + list(messages)
    )
    return {"messages": [response]}


async def _approval_gate(state: AgentState) -> dict:
    """
    Pause execution for human approval before running an expensive tool.
    Uses LangGraph interrupt() — the graph is suspended here until resume()
    is called with a truthy (approved) or falsy (rejected) value.
    """
    last_msg = state["messages"][-1]
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return {}

    tool_call = last_msg.tool_calls[0]
    tool_name = tool_call.get("name", "unknown")
    tool_args = tool_call.get("args", {})

    approved: bool = interrupt({
        "question": f"Approve running '{tool_name}'?",
        "tool": tool_name,
        "args": tool_args,
    })

    if not approved:
        # Inject a synthetic ToolMessage so the LLM knows the call was rejected
        rejection = ToolMessage(
            content=f"User declined to run '{tool_name}'. Do not retry this call.",
            tool_call_id=tool_call.get("id", "rejected"),
            name=tool_name,
        )
        return {"messages": [rejection]}

    return {}


async def _run_tools(state: AgentState, tool_node: ToolNode) -> dict:
    """Execute the pending tool calls via ToolNode."""
    return await tool_node.ainvoke(state)


def _extract_sources(state: AgentState) -> dict:
    """
    Parse the most-recent batch of ToolMessages into SourceRecord objects.
    Applies VECTOR_STORE_RELEVANCE_THRESHOLD filtering to search_storage results.
    """
    existing_count = len(state.get("source_records") or [])
    new_records = _extract_sources_from_tool_messages(
        state["messages"], existing_count
    )
    return {"source_records": new_records}


async def _run_checker(
    state: AgentState, checker: CheckerAgent
) -> dict:
    """
    Validate the draft answer against retrieved sources.  If issues are found,
    replace the last AIMessage content with the corrected answer.
    """
    messages = state["messages"]
    # Find original user query (last HumanMessage)
    original_query = next(
        (m.content for m in reversed(messages) if isinstance(m, HumanMessage)
         and isinstance(m.content, str)),
        "",
    )
    # Find last AI message
    last_ai = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage)),
        None,
    )
    if last_ai is None or not original_query:
        return {}

    draft_answer = (
        last_ai.content if isinstance(last_ai.content, str) else ""
    )
    source_records: list[SourceRecord] = state.get("source_records") or []
    sources_manifest = _build_source_manifest(source_records)

    result: CheckResult = await checker.arun(
        query=original_query,
        draft_answer=draft_answer,
        sources_manifest=sources_manifest,
        source_records=source_records,
    )

    if not result.has_issues:
        return {}

    # Build a corrected AIMessage
    correction_note = ""
    if result.flags:
        correction_note += "\n\n> **Checker flags**: " + "; ".join(result.flags)
    if result.ungrounded_citations:
        correction_note += "\n> **Ungrounded citations removed**: " + ", ".join(
            result.ungrounded_citations
        )
    if result.missing_citations:
        correction_note += "\n> **Suggested citations**: " + "; ".join(
            result.missing_citations
        )

    corrected_content = result.corrected_answer + correction_note
    corrected_ai = AIMessage(
        content=corrected_content,
        id=last_ai.id,
    )
    return {"messages": [corrected_ai]}


async def _finalize(
    state: AgentState,
    config: RunnableConfig,
    llm: Any,
    store: InMemoryStore,
) -> dict:
    """
    Post-processing node:
    1. If message count > MSG_SUMMARIZE_THRESHOLD, condense older messages.
    2. Persist key research findings to the long-term store.
    3. Append a ## Sources section to the last AI message.
    4. Reset source_records for the next turn.
    """
    username = (config.get("configurable") or {}).get("username", "")
    messages = state["messages"]
    updates: dict = {}

    # ── 1. Message summarization ─────────────────────────────────────────────
    if len(messages) > MSG_SUMMARIZE_THRESHOLD:
        old_messages = messages[:-4]  # keep last 4
        summary_prompt = SUMMARIZE_PROMPT.format(
            summary=state.get("summary") or "",
            messages="\n".join(
                f"{type(m).__name__}: {m.content}" for m in old_messages
                if isinstance(m.content, str)
            ),
        )
        try:
            summary_response = await llm.ainvoke(
                [HumanMessage(content=summary_prompt)]
            )
            new_summary = (
                summary_response.content
                if isinstance(summary_response.content, str)
                else state.get("summary", "")
            )
            updates["summary"] = new_summary
            updates["messages"] = [RemoveMessage(id=m.id) for m in old_messages]
        except Exception:
            logger.exception("finalize: summarization failed — keeping messages")

    # ── 2. Long-term memory persistence ─────────────────────────────────────
    turn_tools = _get_turn_tool_names(messages)
    if username and any(t in turn_tools for t in _RESEARCH_TOOLS):
        last_ai = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)), None
        )
        if last_ai and isinstance(last_ai.content, str):
            try:
                await store.aput(
                    (username, "research_notes"),
                    str(uuid.uuid4()),
                    {"memory": last_ai.content[:500]},
                )
            except Exception:
                logger.exception("finalize: store.aput failed — skipping")

    # ── 3. Append ## Sources to last AI message ──────────────────────────────
    source_records: list[SourceRecord] = state.get("source_records") or []
    visible_records = [r for r in source_records if not r.filtered]

    current_messages = messages  # may have been modified by summarization above
    last_ai = next(
        (m for m in reversed(current_messages) if isinstance(m, AIMessage)), None
    )

    if last_ai and visible_records and isinstance(last_ai.content, str):
        # Only list sources that are actually cited in the text ([N])
        cited_ids = set(
            int(m) for m in re.findall(r"\[(\d+)\]", last_ai.content)
        )
        cited_records = [r for r in visible_records if r.ref_id in cited_ids]
        if cited_records:
            ref_lines = "\n".join(
                f"[{r.ref_id}] {r.title} — {r.url}" for r in cited_records
            )
            new_content = last_ai.content.rstrip() + f"\n\n## Sources\n{ref_lines}"
            updated_ai = AIMessage(content=new_content, id=last_ai.id)
            existing_messages = updates.get("messages", [])
            updates["messages"] = list(existing_messages) + [updated_ai]

    # ── 4. Reset source_records for the next turn ────────────────────────────
    # We overwrite the accumulated list with an empty list.
    # Because source_records uses operator.add reducer, we cannot "clear" it
    # directly; instead we track via the graph's state update mechanism.
    # The graph state accumulates but finalize annotates which are "this turn".
    # (Actual clearing would require a custom reducer; for now we keep them
    # in state — they are harmless and useful for time-travel inspection.)

    return updates


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------


def _should_continue(
    state: AgentState,
) -> Literal["approval_gate", "run_tools", "run_checker", "finalize"]:
    """Route after call_model."""
    messages = state["messages"]
    last_msg = messages[-1] if messages else None

    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        # Check if any pending call needs approval
        if any(_is_expensive_call(tc) for tc in last_msg.tool_calls):
            return "approval_gate"
        return "run_tools"

    # No tool calls — check if we should run the checker
    turn_tools = _get_turn_tool_names(messages)
    if any(t in turn_tools for t in _RESEARCH_TOOLS):
        return "run_checker"

    return "finalize"


def _after_approval(
    state: AgentState,
) -> Literal["run_tools", "call_model"]:
    """Route after approval_gate: rejected → back to model; approved → tools."""
    last_msg = state["messages"][-1] if state["messages"] else None
    if isinstance(last_msg, ToolMessage):
        # Rejection was injected — tell the model
        return "call_model"
    return "run_tools"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(
    username: str,
    password: str,
    checkpointer: Any = None,
    store: Any = None,
    config_override: dict | None = None,
) -> Any:
    """
    Build and compile the SciBot LangGraph StateGraph.

    Parameters
    ----------
    username    : scibot username (used to scope long-term memory)
    password    : scibot password
    checkpointer: LangGraph checkpointer (default: MemorySaver)
    store       : LangGraph store (default: InMemoryStore)

    Returns
    -------
    Compiled LangGraph graph.
    """
    _checkpointer = checkpointer or MemorySaver()
    _store = store or InMemoryStore()

    # ── LLM + tools ─────────────────────────────────────────────────────────
    config_dict = resolve_config(username, password, config_override)
    llm = get_llm(config_dict.get("llm"))

    all_tools = build_tools(username, password, config_override)
    researcher_tool = build_researcher_tool(username, password, config_override)
    orchestrator_tools = all_tools + [researcher_tool]

    llm_with_tools = llm.bind_tools(orchestrator_tools)
    tool_node = ToolNode(orchestrator_tools)

    # ── Checker ──────────────────────────────────────────────────────────────
    checker = CheckerAgent(username, password, config_override)

    # ── Node closures ────────────────────────────────────────────────────────

    async def recall_memories(state: AgentState, config: RunnableConfig) -> dict:
        return await _recall_memories(state, config, _store)

    def call_model(state: AgentState) -> dict:
        return _call_model(state, llm_with_tools)

    async def approval_gate(state: AgentState) -> dict:
        return await _approval_gate(state)

    async def run_tools(state: AgentState) -> dict:
        return await _run_tools(state, tool_node)

    def extract_sources(state: AgentState) -> dict:
        return _extract_sources(state)

    async def run_checker(state: AgentState) -> dict:
        return await _run_checker(state, checker)

    async def finalize(state: AgentState, config: RunnableConfig) -> dict:
        return await _finalize(state, config, llm, _store)

    # ── Graph assembly ───────────────────────────────────────────────────────
    builder = StateGraph(AgentState)

    builder.add_node("recall_memories", recall_memories)
    builder.add_node("call_model", call_model)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("run_tools", run_tools)
    builder.add_node("extract_sources", extract_sources)
    builder.add_node("run_checker", run_checker)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "recall_memories")
    builder.add_edge("recall_memories", "call_model")
    builder.add_conditional_edges(
        "call_model",
        _should_continue,
        {
            "approval_gate": "approval_gate",
            "run_tools": "run_tools",
            "run_checker": "run_checker",
            "finalize": "finalize",
        },
    )
    builder.add_conditional_edges(
        "approval_gate",
        _after_approval,
        {
            "run_tools": "run_tools",
            "call_model": "call_model",
        },
    )
    builder.add_edge("run_tools", "extract_sources")
    builder.add_edge("extract_sources", "call_model")
    builder.add_edge("run_checker", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=_checkpointer, store=_store)


# ---------------------------------------------------------------------------
# AgentResponse
# ---------------------------------------------------------------------------


@dataclass
class AgentResponse:
    """Structured return value from OrchestratorAgent.run()."""

    answer: str
    thread_id: str
    verified: bool = True
    confidence: float = 1.0
    flags: list[str] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    interrupted: bool = False
    interrupt_payload: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# OrchestratorAgent
# ---------------------------------------------------------------------------


class OrchestratorAgent:
    """
    High-level interface to the SciBot LangGraph orchestrator.

    Usage
    -----
        agent = OrchestratorAgent("alice", "alice_pw")

        # Single-turn (blocking)
        response = agent.run("Explain the attention mechanism", thread_id="t1")
        print(response.answer)

        # Streaming
        async for chunk in agent.astream("Summarize BERT", thread_id="t1"):
            print(chunk, end="", flush=True)

        # Time travel
        history = agent.get_history("t1")
        new_ckpt = agent.fork_from("t1", history[2].config["configurable"]["checkpoint_id"],
                                   updates={"source_records": []})
    """

    def __init__(
        self,
        username: str,
        password: str,
        checkpointer: Any = None,
        store: Any = None,
        config_override: dict | None = None,
        active_collection_name: str | None = None,
    ) -> None:
        self.username = username
        self._password = password
        self._config_override = config_override
        self._active_collection_name = active_collection_name
        self._checkpointer = checkpointer or MemorySaver()
        self._store = store or InMemoryStore()
        self.graph = build_graph(
            username, password, self._checkpointer, self._store, config_override
        )

    # ── Config helpers ───────────────────────────────────────────────────────

    def _config(self, thread_id: str) -> dict:
        configurable = {
            "thread_id": f"{self.username}:{thread_id}",
            "username": self.username,
        }
        if self._active_collection_name:
            configurable["active_collection_name"] = self._active_collection_name
        return {"configurable": configurable}

    async def afallback_answer(self, query: str, reason: str | None = None) -> str:
        from app.agent.researcher import ResearcherAgent

        researcher = ResearcherAgent(
            self.username,
            self._password,
            self._config_override,
        )
        return await researcher.afallback_answer(query, reason=reason)

    # ── Synchronous run ──────────────────────────────────────────────────────

    def run(self, query: str, thread_id: str = "default") -> AgentResponse:
        """
        Invoke the agent synchronously.  Blocks until the graph reaches END
        or an interrupt.

        Returns AgentResponse with answer, sources, and verification metadata.
        If an interrupt is raised (HITL approval needed), returns an
        AgentResponse with interrupted=True and the interrupt payload.
        """
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._arun_internal(query, thread_id)
        )

    async def _arun_internal(
        self, query: str, thread_id: str
    ) -> AgentResponse:
        config = self._config(thread_id)
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "summary": "",
        }
        try:
            result = await self.graph.ainvoke(initial_state, config)
            return self._build_response(result, thread_id)
        except Exception as exc:
            # Check if this is an interrupt (HITL)
            interrupts = _get_interrupts(exc)
            if interrupts:
                return AgentResponse(
                    answer="",
                    thread_id=thread_id,
                    interrupted=True,
                    interrupt_payload=interrupts[0] if interrupts else {},
                )
            raise

    # ── Async streaming ──────────────────────────────────────────────────────

    async def astream(
        self, query: str, thread_id: str = "default"
    ) -> AsyncIterator[str | dict]:
        """
        Stream the agent's responses.  Yields:
        - str: AI message token chunks
        - dict with type="tool_start": tool execution notification
        - dict with type="sources": source count after extract_sources
        - dict with type="interrupt": HITL interrupt payload
        """
        config = self._config(thread_id)
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "summary": "",
        }
        async for chunk in self.graph.astream(
            initial_state,
            config,
            stream_mode=["messages", "updates"],
        ):
            kind = chunk[0] if isinstance(chunk, tuple) else None
            data = chunk[1] if isinstance(chunk, tuple) else chunk

            if kind == "messages":
                # data is (message_chunk, metadata)
                msg_chunk = data[0] if isinstance(data, tuple) else data
                metadata = data[1] if isinstance(data, tuple) and len(data) > 1 else {}
                content = getattr(msg_chunk, "content", "")
                if (
                    content
                    and isinstance(content, str)
                    and isinstance(msg_chunk, (AIMessage, AIMessageChunk))
                    and metadata.get("langgraph_node") == "call_model"
                ):
                    yield content

            elif kind == "updates":
                if "run_tools" in data:
                    tool_msgs = [
                        m for m in (data["run_tools"].get("messages") or [])
                        if isinstance(m, ToolMessage)
                    ]
                    for tm in tool_msgs:
                        yield {
                            "type": "tool_start",
                            "tool": getattr(tm, "name", ""),
                        }

                if "extract_sources" in data:
                    new_records = data["extract_sources"].get("source_records", [])
                    visible = [r for r in new_records if not r.filtered]
                    yield {
                        "type": "sources",
                        "count": len(visible),
                        "filtered": len(new_records) - len(visible),
                    }

            # Surface interrupts
            if isinstance(data, dict) and "__interrupt__" in data:
                yield {"type": "interrupt", "payload": data["__interrupt__"]}

    # ── Resume (HITL) ────────────────────────────────────────────────────────

    async def resume(
        self, response: Any, thread_id: str = "default"
    ) -> AgentResponse:
        """
        Resume a graph that was paused by an interrupt() call.

        Parameters
        ----------
        response  : the value passed back to interrupt() — True to approve,
                    False to reject, or any other JSON-serialisable value.
        thread_id : must match the thread_id used in the interrupted run.
        """
        config = self._config(thread_id)
        result = await self.graph.ainvoke(Command(resume=response), config)
        return self._build_response(result, thread_id)

    # ── Time travel ──────────────────────────────────────────────────────────

    def get_history(self, thread_id: str) -> list:
        """Return a list of StateSnapshot objects for the given thread."""
        config = self._config(thread_id)
        return list(self.graph.get_state_history(config))

    def get_state(self, thread_id: str):
        """Return the current StateSnapshot for the given thread."""
        return self.graph.get_state(self._config(thread_id))

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _build_response(self, result: dict, thread_id: str) -> AgentResponse:
        messages = result.get("messages") or []
        last_ai = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)), None
        )
        answer = (
            last_ai.content if last_ai and isinstance(last_ai.content, str) else ""
        )
        source_records: list[SourceRecord] = result.get("source_records") or []
        return AgentResponse(
            answer=answer,
            thread_id=thread_id,
            sources=source_records,
        )


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------


def _get_interrupts(exc: Exception) -> list[dict]:
    """Extract interrupt payloads from a GraphInterrupt exception if possible."""
    # LangGraph raises langgraph.errors.GraphInterrupt which carries .interrupts
    interrupts = getattr(exc, "interrupts", None)
    if isinstance(interrupts, list):
        return [
            i.value if hasattr(i, "value") else i
            for i in interrupts
        ]
    return []
