"""
Web search tool for scibot.

Backend selection (in priority order):
  1. Tavily  — if TAVILY_API_KEY is set
  2. SerpAPI — if SERPAPI_API_KEY is set
  3. DuckDuckGo — always available, no key required

All results are post-filtered to a domain whitelist.  The default whitelist
covers academic and trusted reference sources; callers may extend it via
``extra_domains``.

Input
-----
query         : str   — search query
max_results   : int   — maximum number of results to return (default 5)
extra_domains : list  — additional allowed domains appended to the default
                        whitelist for this call only
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import tool
from pydantic import BaseModel, Field

# ── Default domain whitelist ──────────────────────────────────────────────────

_DEFAULT_WHITELIST: list[str] = [
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "wikipedia.org",
    "github.com",
    "stackoverflow.com",
    "stackexchange.com",
    "nature.com",
    "sciencedirect.com",
    "springer.com",
    "scholar.google.com",
    "semanticscholar.org",
    "biorxiv.org",
    "medrxiv.org",
    "plos.org",
    "frontiersin.org",
    "ieee.org",
    "acm.org",
]

# Top-level domains used to build DuckDuckGo site: hints.
# Must be a subset of _DEFAULT_WHITELIST for coherent filtering.
_DDG_SITE_HINTS = [
    "arxiv.org", "wikipedia.org", "github.com", "stackoverflow.com",
    "stackexchange.com", "semanticscholar.org", "nature.com",
    "pubmed.ncbi.nlm.nih.gov", "biorxiv.org", "springer.com",
]


def _domain_allowed(url: str, whitelist: list[str]) -> bool:
    """Return True if *url*'s hostname matches any entry in *whitelist*."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower().lstrip("www.")
    return any(host == d or host.endswith("." + d) for d in whitelist)


def _format_results(results: list[dict], whitelist: list[str], max_results: int) -> str:
    """Filter results to whitelist and return a numbered string."""
    filtered: list[dict] = []
    for r in results:
        url = r.get("url") or r.get("link") or r.get("href") or ""
        if _domain_allowed(url, whitelist):
            filtered.append(r)
        if len(filtered) >= max_results:
            break

    if not filtered:
        return "No results found on whitelisted domains."

    lines: list[str] = []
    for i, r in enumerate(filtered, 1):
        title   = r.get("title") or r.get("name") or "(no title)"
        url     = r.get("url") or r.get("link") or r.get("href") or ""
        snippet = r.get("content") or r.get("snippet") or r.get("body") or r.get("description") or ""
        # Collapse whitespace in snippet
        snippet = re.sub(r"\s+", " ", snippet).strip()[:300]
        lines.append(f"{i}. {title}\n   URL: {url}\n   {snippet}")
    return "\n\n".join(lines)


def _run_tavily(query: str, max_results: int, api_key: str) -> list[dict]:
    from langchain_community.tools.tavily_search import TavilySearchResults
    tool_instance = TavilySearchResults(
        max_results=max_results * 2,  # over-fetch; we filter after
        tavily_api_key=api_key,
    )
    raw = tool_instance.invoke({"query": query})
    if isinstance(raw, list):
        return raw
    return []


def _run_serp(query: str, max_results: int, api_key: str) -> list[dict]:
    from langchain_community.utilities import SerpAPIWrapper
    wrapper = SerpAPIWrapper(serpapi_api_key=api_key)
    raw = wrapper.results(query)
    items: list[dict] = []
    for r in (raw.get("organic_results") or []):
        items.append({
            "title": r.get("title", ""),
            "url":   r.get("link", ""),
            "snippet": r.get("snippet", ""),
        })
        if len(items) >= max_results * 2:
            break
    return items


def _run_duckduckgo(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS

    # Append site: hints so DDG preferentially surfaces whitelisted domains.
    site_expr = " OR ".join(f"site:{d}" for d in _DDG_SITE_HINTS)
    guided_query = f"{query} ({site_expr})"

    items: list[dict] = []
    with DDGS() as ddgs:
        for r in ddgs.text(guided_query, max_results=max_results * 2):
            items.append({
                "title": r.get("title", ""),
                "url":   r.get("href", ""),
                "snippet": r.get("body", ""),
            })
    return items


# ── Tool ─────────────────────────────────────────────────────────────────────

class WebSearchInput(BaseModel):
    query: str = Field(description="The search query.")
    max_results: int = Field(default=5, description="Maximum number of whitelisted results to return.")
    extra_domains: list[str] = Field(
        default_factory=list,
        description="Additional trusted domains to include in the whitelist for this call.",
    )
    username: str | None = Field(default=None, description="Internal username binding.")
    password: str | None = Field(default=None, description="Internal password binding.")
    config_override: dict | None = Field(default=None, description="Internal chat-level config override.")


@tool("web_search", args_schema=WebSearchInput)
def web_search(
    query: str,
    max_results: int = 5,
    extra_domains: list[str] | None = None,
    username: str | None = None,
    password: str | None = None,
    config_override: dict | None = None,
) -> str:
    """
    Search the web for information and return results from trusted academic and
    reference domains.  Automatically selects the best available search backend
    (Tavily > SerpAPI > DuckDuckGo).

    Returns a numbered list of results, each with title, URL, and a short
    snippet.  Only results from the whitelisted domains are included.
    """
    from app.users.config import resolve_config

    effective_cfg = resolve_config(username, password, config_override)
    external_keys = effective_cfg.get("external_keys") or {}
    search_cfg = effective_cfg.get("search") or {}
    selected_tool = str(search_cfg.get("tool") or "").lower()
    tavily_api_key = external_keys.get("TAVILY_API_KEY") or ""
    serpapi_api_key = external_keys.get("SERPAPI_API_KEY") or ""

    whitelist = _DEFAULT_WHITELIST + (extra_domains or [])

    errors: list[str] = []

    backend_order: list[str]
    if selected_tool == "tavily":
        backend_order = ["tavily", "serp", "duckduckgo"]
    elif selected_tool == "serp":
        backend_order = ["serp", "tavily", "duckduckgo"]
    else:
        backend_order = ["duckduckgo", "tavily", "serp"]

    for backend in backend_order:
        if backend == "tavily":
            if not tavily_api_key:
                if selected_tool == "tavily":
                    errors.append("Tavily selected but TAVILY_API_KEY is not configured.")
                continue
            try:
                raw = _run_tavily(query, max_results, tavily_api_key)
                return _format_results(raw, whitelist, max_results)
            except Exception as exc:
                errors.append(f"Tavily error: {exc}")
            continue

        if backend == "serp":
            if not serpapi_api_key:
                if selected_tool == "serp":
                    errors.append("SerpAPI selected but SERPAPI_API_KEY is not configured.")
                continue
            try:
                raw = _run_serp(query, max_results, serpapi_api_key)
                return _format_results(raw, whitelist, max_results)
            except Exception as exc:
                errors.append(f"SerpAPI error: {exc}")
            continue

        try:
            raw = _run_duckduckgo(query, max_results)
            return _format_results(raw, whitelist, max_results)
        except Exception as exc:
            errors.append(f"DuckDuckGo error: {exc}")

    return "Web search failed.\n" + "\n".join(errors)
