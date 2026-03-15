"""
app.tools — LangChain tool registry for the scibot agent.

Exports
-------
All tool functions are importable directly:

    from app.tools.web_search    import web_search
    from app.tools.arxiv_search  import arxiv_search
    from app.tools.pubmed_search import pubmed_search
    from app.tools.get_data      import get_data
    from app.tools.analyze_data  import analyze_data
    from app.tools.search_storage import search_storage

``build_tools(username, password)`` returns the full list of
``StructuredTool`` instances ready to be passed to any LangChain agent.
Auth-dependent tools are wrapped in closures that pre-fill ``username`` and
``password`` so the agent does not need to supply them explicitly.

Usage example
-------------
    from app.tools import build_tools

    tools = build_tools("alice", "alice_pw")
    # Pass to a LangChain agent
    agent = create_tool_calling_agent(llm, tools, prompt)
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from app.tools.analyze_data  import analyze_data
from app.tools.arxiv_search  import arxiv_search
from app.tools.get_data      import get_data
from app.tools.pubmed_search import pubmed_search
from app.tools.search_storage import search_storage
from app.tools.web_search    import web_search

__all__ = [
    "web_search",
    "arxiv_search",
    "pubmed_search",
    "get_data",
    "analyze_data",
    "search_storage",
    "build_tools",
]


def build_tools(username: str, password: str) -> list[StructuredTool]:
    """
    Return a list of LangChain StructuredTool instances configured for the
    given user.

    Auth-dependent tools (``get_data``, ``analyze_data``, ``search_storage``)
    are wrapped so that ``username`` and ``password`` are pre-filled from the
    closure — the agent only needs to supply the domain-specific arguments.

    Parameters
    ----------
    username : scibot username (used to decrypt per-user config)
    password : scibot password

    Returns
    -------
    list of StructuredTool — pass directly to a LangChain agent constructor.
    """

    # ── Wrappers that pre-fill credentials ───────────────────────────────────

    def _get_data_bound(
        source_type: str,
        file_path: str | None = None,
        alias: str | None = None,
        sql_query: str | None = None,
        mongo_filter: dict | None = None,
        limit: int | None = None,
    ) -> str:
        return get_data.invoke({
            "source_type":  source_type,
            "file_path":    file_path,
            "alias":        alias,
            "sql_query":    sql_query,
            "mongo_filter": mongo_filter,
            "limit":        limit,
            "username":     username,
            "password":     password,
        })

    def _analyze_data_bound(
        data_handle: str,
        query: str | None = None,
    ) -> str:
        return analyze_data.invoke({
            "data_handle": data_handle,
            "query":       query,
            "username":    username,
            "password":    password,
        })

    async def _search_storage_bound(
        query: str,
        collection_name: str,
        k: int = 5,
        score_threshold: float = 0.3,
        source_id: str | None = None,
        source_type: str | None = None,
        filter: dict | None = None,
    ) -> str:
        return await search_storage.ainvoke({
            "query":           query,
            "username":        username,
            "password":        password,
            "collection_name": collection_name,
            "k":               k,
            "score_threshold": score_threshold,
            "source_id":       source_id,
            "source_type":     source_type,
            "filter":          filter,
        })

    # ── Build bound StructuredTools ───────────────────────────────────────────

    bound_get_data = StructuredTool.from_function(
        func=_get_data_bound,
        name="get_data",
        description=(
            "Load data from a CSV file, JSON file, MongoDB collection, or PostgreSQL "
            "table into a pandas DataFrame.  Returns a data_handle to pass to analyze_data. "
            "For csv/json provide file_path.  For mongodb/postgres provide the alias name "
            "configured in your account."
        ),
    )

    bound_analyze_data = StructuredTool.from_function(
        func=_analyze_data_bound,
        name="analyze_data",
        description=(
            "Perform exploratory data analysis on a DataFrame (loaded by get_data) and "
            "return pandas EDA statistics plus LLM-generated insights.  Pass data_handle "
            "from get_data.  Optionally provide a query to focus the analysis."
        ),
    )

    bound_search_storage = StructuredTool.from_function(
        coroutine=_search_storage_bound,
        name="search_storage",
        description=(
            "Search a scibot collection using parallel semantic + MMR retrieval, then "
            "re-rank with the configured LLM.  Returns the top-k most relevant chunks "
            "with source metadata and content previews.  Filter by source_id or source_type "
            "for targeted retrieval."
        ),
    )

    return [
        web_search,
        arxiv_search,
        pubmed_search,
        bound_get_data,
        bound_analyze_data,
        bound_search_storage,
    ]
