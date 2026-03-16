"""
app.agent.researcher — Specialized deep-research sub-agent.

ResearcherAgent wraps a LangChain AgentExecutor that has access to four
retrieval tools (search_storage, web_search, arxiv_search, pubmed_search).
It is exposed to the orchestrator as a single StructuredTool ("invoke_researcher")
so that the orchestrator can delegate complex multi-source queries to it.
"""

from __future__ import annotations

import asyncio
import re

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

try:
    from langgraph.errors import GraphRecursionError
except Exception:  # pragma: no cover - defensive fallback for older langgraph versions
    class GraphRecursionError(RuntimeError):
        pass

from app.config.llm_model import get_llm
from app.tools import build_tools
from app.users.config import resolve_config

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

RESEARCHER_SYSTEM = """\
You are a specialized scientific researcher sub-agent for SciBot. \
Your job is to gather comprehensive, well-sourced evidence on the given query.

Search strategy (follow in order):
1. First search the user's personal knowledge store (search_storage) for \
   directly relevant documents.
2. Then search scientific literature via arxiv_search and pubmed_search.
3. Finally, use web_search only to fill remaining gaps.

Output requirements:
- Return a detailed research summary with FULL citations for every claim.
- For each source include: title, authors (if known), year, URL, \
  arxiv ID / PubMed PMID where available, and a key excerpt.
- If a source has a vector score below 0.45, omit it from your summary.
- Do NOT fabricate or hallucinate sources.
- Stop when you have sufficient evidence (max 6 tool calls).
"""

RESEARCHER_RECURSION_LIMIT = 9

_READING_LIST_RE = re.compile(
    r"(which|what|recommend|suggest|list|best|top).{0,40}(paper|papers|reading)|"
    r"(paper|papers).{0,40}(should i read|to read|for reading|to understand|to learn|common to|related to)|"
    r"reading list",
    re.IGNORECASE | re.DOTALL,
)

_BIOMEDICAL_RE = re.compile(
    r"\b(pubmed|biomed|biomedical|clinical|disease|cancer|protein|gene|genomic|drug|patient|medical)\b",
    re.IGNORECASE,
)


def _looks_like_reading_list_query(query: str) -> bool:
    return bool(_READING_LIST_RE.search(query or ""))


def _needs_pubmed(query: str) -> bool:
    return bool(_BIOMEDICAL_RE.search(query or ""))


def _stringify_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") if isinstance(item.get("text"), str) else ""
                if text:
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content or "")

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ResearcherAgent:
    """
    A standalone research sub-agent backed by a LangChain AgentExecutor.

    It uses the four retrieval tools (search_storage, web_search,
    arxiv_search, pubmed_search) and is intentionally kept separate from
    the orchestrator's graph so that HITL/interrupts are not needed inside
    the sub-research loop.
    """

    def __init__(self, username: str, password: str, config_override: dict | None = None) -> None:
        self.username = username

        # Build LLM from user / env config -----------------------------------
        config = resolve_config(username, password, config_override)
        self.llm = get_llm(config.get("llm"))

        # Build tool subset (researcher only gets retrieval tools) -----------
        all_tools = build_tools(username, password, config_override)
        researcher_tool_names = {
            "search_storage",
            "web_search",
            "arxiv_search",
            "pubmed_search",
        }
        tools = [t for t in all_tools if t.name in researcher_tool_names]
        self._tools_by_name = {tool.name: tool for tool in tools}

        # Build the agent graph using LangChain 1.x create_agent -------------
        # create_agent returns a compiled LangGraph StateGraph equivalent to
        # the old AgentExecutor; max tool iterations controlled via recursion_limit.
        self._graph = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=RESEARCHER_SYSTEM,
        )
        # Keep the sub-agent bounded tightly; simple reading-list queries take
        # the direct fallback path below instead of spending multiple graph steps.
        self._run_config = {"recursion_limit": RESEARCHER_RECURSION_LIMIT}

    async def afallback_answer(self, query: str, reason: str | None = None) -> str:
        sections: list[str] = []

        arxiv_tool = self._tools_by_name.get("arxiv_search")
        if arxiv_tool is not None:
            try:
                arxiv_result = await arxiv_tool.ainvoke({
                    "query": query,
                    "max_results": 5,
                    "fetch_full": False,
                })
                if isinstance(arxiv_result, str) and arxiv_result.strip():
                    sections.append("arXiv results:\n" + arxiv_result.strip())
            except Exception as exc:
                sections.append(f"arXiv results unavailable: {exc}")

        if _needs_pubmed(query):
            pubmed_tool = self._tools_by_name.get("pubmed_search")
            if pubmed_tool is not None:
                try:
                    pubmed_result = await pubmed_tool.ainvoke({
                        "query": query,
                        "max_results": 5,
                        "fetch_full": False,
                    })
                    if isinstance(pubmed_result, str) and pubmed_result.strip():
                        sections.append("PubMed results:\n" + pubmed_result.strip())
                except Exception as exc:
                    sections.append(f"PubMed results unavailable: {exc}")

        if not sections:
            return (
                "I could not complete the full research graph, and direct literature "
                "search also failed. Please retry the question or narrow the topic."
            )

        prompt = (
            "Prepare a concise reading list using only the papers present in the search "
            "results below. Do not invent papers. Prefer canonical or foundational papers "
            "when they are present.\n\n"
            "Return:\n"
            "1. A one-sentence overview.\n"
            "2. Three to five recommended papers with title, year if available, a short "
            "reason, and URL.\n"
            "3. If appropriate, end with 'If you only read two:' and name the top two."
        )

        if reason:
            prompt += f"\n\nContext: the full research graph hit its recursion limit ({reason})."

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(
                    content=(
                        f"User question: {query}\n\n"
                        f"Search results:\n\n{chr(10).join(sections)}"
                    )
                ),
            ])

            answer = _stringify_content(getattr(response, "content", "")).strip()
            if answer:
                return answer
        except Exception:
            pass

        return "\n\n".join(sections)

    def run(self, query: str) -> str:
        """
        Run the researcher synchronously and return a formatted research summary.
        """
        if _looks_like_reading_list_query(query):
            return asyncio.run(self.afallback_answer(query))

        try:
            result = self._graph.invoke(
                {"messages": [HumanMessage(content=query)]},
                self._run_config,
            )
        except GraphRecursionError as exc:
            return asyncio.run(self.afallback_answer(query, reason=str(exc)))

        messages = result.get("messages") or []
        from langchain_core.messages import AIMessage
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        return last_ai.content if last_ai and isinstance(last_ai.content, str) else ""

    async def arun(self, query: str) -> str:
        """
        Run the researcher asynchronously and return a formatted research summary.
        """
        if _looks_like_reading_list_query(query):
            return await self.afallback_answer(query)

        try:
            result = await self._graph.ainvoke(
                {"messages": [HumanMessage(content=query)]},
                self._run_config,
            )
        except GraphRecursionError as exc:
            return await self.afallback_answer(query, reason=str(exc))

        messages = result.get("messages") or []
        from langchain_core.messages import AIMessage
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        return last_ai.content if last_ai and isinstance(last_ai.content, str) else ""


# ---------------------------------------------------------------------------
# Factory — exposed to the orchestrator as a StructuredTool
# ---------------------------------------------------------------------------


class _ResearcherInput(BaseModel):
    query: str


def build_researcher_tool(
    username: str,
    password: str,
    config_override: dict | None = None,
) -> StructuredTool:
    """
    Build a StructuredTool named ``invoke_researcher`` that wraps a
    ResearcherAgent instance.  The orchestrator adds this to its tool set
    alongside the direct retrieval tools.
    """
    researcher = ResearcherAgent(username, password, config_override)

    async def _invoke_researcher(query: str) -> str:
        """
        Delegate a complex multi-source research query to the specialized
        ResearcherAgent sub-agent.  Returns a detailed research summary with
        full citations (title, URL, key excerpt) for every claim.  Use this
        tool when the question requires synthesizing information across
        multiple papers or sources, rather than a single direct lookup.
        """
        return await researcher.arun(query)

    return StructuredTool.from_function(
        coroutine=_invoke_researcher,
        name="invoke_researcher",
        description=(
            "Delegate a complex multi-source research query to the specialized "
            "ResearcherAgent sub-agent. Returns a detailed research summary with "
            "full citations (title, URL, key excerpt) for every claim. Use this "
            "tool when the question requires synthesizing information across "
            "multiple papers or sources, rather than a single direct lookup."
        ),
        args_schema=_ResearcherInput,
    )
