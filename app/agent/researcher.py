"""
app.agent.researcher — Specialized deep-research sub-agent.

ResearcherAgent wraps a LangChain AgentExecutor that has access to four
retrieval tools (search_storage, web_search, arxiv_search, pubmed_search).
It is exposed to the orchestrator as a single StructuredTool ("invoke_researcher")
so that the orchestrator can delegate complex multi-source queries to it.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

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

        # Build the agent graph using LangChain 1.x create_agent -------------
        # create_agent returns a compiled LangGraph StateGraph equivalent to
        # the old AgentExecutor; max tool iterations controlled via recursion_limit.
        self._graph = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=RESEARCHER_SYSTEM,
        )
        # Each tool call occupies 2 steps (model + tool), so 6 tool calls ≈ 13.
        self._run_config = {"recursion_limit": 13}

    def run(self, query: str) -> str:
        """
        Run the researcher synchronously and return a formatted research summary.
        """
        result = self._graph.invoke(
            {"messages": [HumanMessage(content=query)]},
            self._run_config,
        )
        messages = result.get("messages") or []
        from langchain_core.messages import AIMessage
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        return last_ai.content if last_ai and isinstance(last_ai.content, str) else ""

    async def arun(self, query: str) -> str:
        """
        Run the researcher asynchronously and return a formatted research summary.
        """
        result = await self._graph.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            self._run_config,
        )
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
