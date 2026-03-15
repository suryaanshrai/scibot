"""
arXiv search tool for scibot.

Two-step hybrid approach:
  1. Keyword search via LangChain ArxivRetriever — fast, returns title/abstract
     metadata for up to *max_results* papers.
  2. Optional full-text fetch via ArxivSource.fetch() — downloads + parses the
     PDF via DoclingLoader and optionally traverses the reference graph.

Input
-----
query        : str  — keyword / natural-language query
max_results  : int  — number of papers from the keyword search (default 5)
fetch_full   : bool — if True, fetch full PDF text for the top result
top_n_refs   : int  — (requires fetch_full) number of top-cited references to
                      return alongside the primary paper (0 = skip)
depth        : int  — (requires fetch_full) reference graph depth to traverse
                      (0 = skip, 1 = direct refs, 2 = refs of refs, …)
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field


# ── Input schema ──────────────────────────────────────────────────────────────

class ArxivSearchInput(BaseModel):
    query: str = Field(description="Keyword or natural-language search query.")
    max_results: int = Field(default=5, description="Number of papers to retrieve.")
    fetch_full: bool = Field(
        default=False,
        description=(
            "If True, download and parse the full PDF for the top result. "
            "Slower but returns complete paper text."
        ),
    )
    top_n_refs: int = Field(
        default=0,
        description="Number of top-cited references to fetch (only used when fetch_full=True).",
    )
    depth: int = Field(
        default=0,
        description="Reference graph traversal depth (only used when fetch_full=True).",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_doc(meta: dict, content_preview: str, index: int) -> str:
    """Format a single paper block for output."""
    title    = meta.get("Title") or meta.get("title") or "(no title)"
    authors  = meta.get("Authors") or meta.get("authors") or []
    if isinstance(authors, list):
        authors_str = ", ".join(str(a) for a in authors[:5])
        if len(authors) > 5:
            authors_str += f" … (+{len(authors)-5} more)"
    else:
        authors_str = str(authors)
    year         = meta.get("Published") or meta.get("year") or ""
    arxiv_id     = meta.get("arxiv_id") or meta.get("entry_id") or meta.get("Entry ID") or ""
    source_url   = meta.get("source_url") or meta.get("Entry ID") or meta.get("entry_id") or ""
    content_type = meta.get("content_type", "abstract")
    cites        = meta.get("citation_count")

    lines = [
        f"[{index}] {title}",
        f"    Authors : {authors_str}",
        f"    Year    : {year}",
        f"    arXiv ID: {arxiv_id}",
        f"    URL     : {source_url}",
        f"    Type    : {content_type}",
    ]
    if cites is not None:
        lines.append(f"    Citations: {cites}")
    lines.append(f"    ---")
    lines.append(f"    {content_preview[:600].strip()}")
    return "\n".join(lines)


# ── Tool ─────────────────────────────────────────────────────────────────────

@tool("arxiv_search", args_schema=ArxivSearchInput)
def arxiv_search(
    query: str,
    max_results: int = 5,
    fetch_full: bool = False,
    top_n_refs: int = 0,
    depth: int = 0,
) -> str:
    """
    Search arXiv for research papers matching a keyword or natural-language
    query.

    By default returns titles, authors, year and abstracts for the top matches.
    Set fetch_full=True to additionally download and parse the full PDF of the
    top result (much slower but returns complete paper content).  When
    fetch_full=True you can also set top_n_refs and depth to retrieve and rank
    referenced papers by citation count.
    """
    from langchain_community.retrievers import ArxivRetriever

    # ── Step 1: keyword search ────────────────────────────────────────────────
    try:
        retriever = ArxivRetriever(load_max_docs=max_results, get_full_documents=False)
        docs = retriever.invoke(query)
    except Exception as exc:
        return f"arXiv search failed: {exc}"

    if not docs:
        return "No arXiv results found for that query."

    sections: list[str] = [f"arXiv search results for: {query!r}\n"]

    for i, doc in enumerate(docs, 1):
        sections.append(_format_doc(doc.metadata, doc.page_content, i))

    # ── Step 2: optional full fetch of top result ─────────────────────────────
    if fetch_full and docs:
        from app.sources.arxiv import ArxivSource, _parse_arxiv_id

        top_meta = docs[0].metadata
        # ArxivRetriever stores entry_id in metadata["Entry ID"]
        entry_id = (
            top_meta.get("Entry ID")
            or top_meta.get("entry_id")
            or top_meta.get("arxiv_id")
            or ""
        )
        if entry_id:
            try:
                arxiv_id = _parse_arxiv_id(entry_id)
                source   = ArxivSource()
                result   = source.fetch(arxiv_id, top_n=top_n_refs, depth=depth)

                primary = result["primary"]
                sections.append(
                    "\n── Full text (top result) ──────────────────────────────────────────────"
                )
                sections.append(_format_doc(primary.metadata, primary.page_content, 1))

                if result["references"]:
                    sections.append(
                        f"\n── Top {len(result['references'])} references (by citation count) ──"
                    )
                    for j, ref in enumerate(result["references"], 1):
                        sections.append(
                            _format_doc(ref.metadata, ref.page_content, j)
                        )
            except Exception as exc:
                sections.append(f"\n[Full-text fetch failed: {exc}]")

    return "\n\n".join(sections)
