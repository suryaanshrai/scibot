"""
PubMed search tool for scibot.

Two-step approach:
  1. NCBI ESearch — keyword search returning a ranked list of PMIDs.
  2. NCBI EFetch — fetch title, authors, year and abstract for each PMID
     using helpers from app.sources.pubmed.

Optionally (fetch_full=True) the top-ranked result is passed to
PubmedSource.fetch() which attempts to retrieve the full PMC text and
can follow the reference graph.

Input
-----
query        : str  — keyword / natural-language query
max_results  : int  — number of papers to retrieve (default 5)
fetch_full   : bool — if True, fetch full PMC text for the top result
top_n_refs   : int  — (requires fetch_full) top-cited references to include
depth        : int  — (requires fetch_full) reference graph depth
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# Reuse helpers from the source adapter — avoids duplicating NCBI logic
from app.sources.pubmed import (
    _NCBI_BASE,
    _NCBI_DELAY,
    _load_pubmed_abstract,
    _ncbi_params,
)


# ── Input schema ──────────────────────────────────────────────────────────────

class PubmedSearchInput(BaseModel):
    query: str = Field(description="Keyword or natural-language search query.")
    max_results: int = Field(default=5, description="Number of papers to retrieve.")
    fetch_full: bool = Field(
        default=False,
        description=(
            "If True, fetch full PMC text for the top result. "
            "Slower but returns complete paper content."
        ),
    )
    top_n_refs: int = Field(
        default=0,
        description="Number of top-cited references to return (only used when fetch_full=True).",
    )
    depth: int = Field(
        default=0,
        description="Reference graph traversal depth (only used when fetch_full=True).",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esearch(query: str, max_results: int) -> list[str]:
    """Run NCBI ESearch and return a list of PMIDs in relevance order."""
    time.sleep(_NCBI_DELAY)
    resp = requests.get(
        f"{_NCBI_BASE}/esearch.fcgi",
        params=_ncbi_params({
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "xml",
            "sort": "relevance",
        }),
        timeout=20,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    return [el.text.strip() for el in root.findall(".//Id") if el.text]


def _format_paper(meta: dict, content_preview: str, index: int) -> str:
    """Format a single paper block for output."""
    title    = meta.get("title") or "(no title)"
    authors  = meta.get("authors") or []
    authors_str = ", ".join(str(a) for a in authors[:5])
    if len(authors) > 5:
        authors_str += f" … (+{len(authors)-5} more)"
    year         = meta.get("year") or ""
    pmid         = meta.get("pmid") or ""
    source_url   = meta.get("source_url") or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    content_type = meta.get("content_type", "abstract")
    cites        = meta.get("citation_count")

    lines = [
        f"[{index}] {title}",
        f"    Authors : {authors_str}",
        f"    Year    : {year}",
        f"    PMID    : {pmid}",
        f"    URL     : {source_url}",
        f"    Type    : {content_type}",
    ]
    if cites is not None:
        lines.append(f"    Citations: {cites}")
    lines.append(f"    ---")
    lines.append(f"    {content_preview[:600].strip()}")
    return "\n".join(lines)


# ── Tool ─────────────────────────────────────────────────────────────────────

@tool("pubmed_search", args_schema=PubmedSearchInput)
def pubmed_search(
    query: str,
    max_results: int = 5,
    fetch_full: bool = False,
    top_n_refs: int = 0,
    depth: int = 0,
) -> str:
    """
    Search PubMed for biomedical literature matching a keyword or
    natural-language query.

    Returns ranked results with title, authors, year, PMID, URL and abstract.
    Set fetch_full=True to additionally retrieve full PMC text for the top
    result.  When fetch_full=True you can also set top_n_refs and depth to
    retrieve and rank referenced papers by citation count.
    """
    # ── Step 1: ESearch ───────────────────────────────────────────────────────
    try:
        pmids = _esearch(query, max_results)
    except Exception as exc:
        return f"PubMed search failed: {exc}"

    if not pmids:
        return "No PubMed results found for that query."

    sections: list[str] = [f"PubMed search results for: {query!r}\n"]

    # ── Step 2: EFetch abstracts for all returned PMIDs ───────────────────────
    papers: list[tuple[str, dict]] = []
    for pmid in pmids:
        try:
            abstract, meta = _load_pubmed_abstract(pmid)
            papers.append((abstract, meta))
        except Exception:
            continue

    for i, (abstract, meta) in enumerate(papers, 1):
        sections.append(_format_paper(meta, abstract, i))

    # ── Step 3: optional full fetch of top result ─────────────────────────────
    if fetch_full and pmids:
        from app.sources.pubmed import PubmedSource

        top_pmid = pmids[0]
        try:
            source = PubmedSource()
            result = source.fetch(top_pmid, top_n=top_n_refs, depth=depth)

            primary = result["primary"]
            sections.append(
                "\n── Full text (top result) ──────────────────────────────────────────────"
            )
            sections.append(_format_paper(primary.metadata, primary.page_content, 1))

            if result["references"]:
                sections.append(
                    f"\n── Top {len(result['references'])} references (by citation count) ──"
                )
                for j, ref in enumerate(result["references"], 1):
                    sections.append(_format_paper(ref.metadata, ref.page_content, j))
        except Exception as exc:
            sections.append(f"\n[Full-text fetch failed: {exc}]")

    return "\n\n".join(sections)
