"""
ArXiv source adapter.

Supports:
  fetch(url)                                  -> Document
  fetch_with_references(url, top_n, depth)    -> FetchResult

URL/ID formats accepted:
  https://arxiv.org/abs/1706.03762
  https://arxiv.org/abs/1706.03762v2
  https://arxiv.org/pdf/1706.03762
  https://arxiv.org/pdf/1706.03762.pdf
  arxiv:1706.03762
  1706.03762
"""

from __future__ import annotations

import logging
import re
import tempfile
import os

import requests
import arxiv as arxiv_lib
from langchain_core.documents import Document

from app.sources.base import (
    FetchResult,
    RefNode,
    SemanticScholarClient,
    collect_references_arxiv,
    make_document,
)

logger = logging.getLogger(__name__)

# Match bare arXiv IDs: old-style (hep-th/9901001) and new-style (1706.03762[v2])
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:|^)"  # optional prefix
    r"([a-z\-]+/\d{7}|\d{4}\.\d{4,5})"       # the ID itself
    r"(?:v\d+)?(?:\.pdf)?$",                   # optional version / extension
    re.IGNORECASE,
)


def _parse_arxiv_id(url: str) -> str:
    """Extract a normalised arXiv ID from any supported URL/string format."""
    url = url.strip()
    m = _ARXIV_ID_RE.search(url)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot parse arXiv ID from: {url!r}")


def _fetch_paper(arxiv_id: str, s2_client: SemanticScholarClient | None = None) -> Document:
    """
    Fetch an arXiv paper and return a Document.

    Uses `arxiv.Search(id_list=[arxiv_id])` for an exact ID lookup (not a text
    search), so the returned paper is guaranteed to match the requested ID.

    Content priority:
      1. Full text from DoclingLoader (structure-aware, handles math/tables)
      2. The PyMuPDF text returned by the arxiv library download
      3. Abstract only (final fallback)
    """
    client = arxiv_lib.Client()
    results = list(client.results(arxiv_lib.Search(id_list=[arxiv_id], max_results=1)))
    if not results:
        raise ValueError(f"No arXiv result found for ID: {arxiv_id}")

    result = results[0]

    # Citation count from Semantic Scholar
    citation_count = 0
    if s2_client:
        s2 = s2_client.get_paper_by_arxiv(arxiv_id)
        if s2:
            citation_count = s2.get("citationCount") or 0

    metadata: dict = {
        "arxiv_id": arxiv_id,
        "title": result.title,
        "authors": [str(a) for a in result.authors],
        "year": result.published.year if result.published else None,
        "abstract": result.summary,
        "doi": result.doi or "",
        "source_url": result.entry_id,
        "paper_type": "arxiv",
        "citation_count": citation_count,
    }

    # Primary: DoclingLoader for richer, structure-aware full text
    full_text = _try_docling_pdf(result.pdf_url)
    if full_text:
        metadata["content_type"] = "full_text"
        return make_document(full_text, metadata)

    # Fallback: abstract only
    metadata["content_type"] = "abstract"
    return make_document(result.summary, metadata)


def _try_docling_pdf(pdf_url: str) -> str | None:
    """
    Download an arXiv PDF then parse it locally via parse_pdf_local (pdf.py).
    Returns None on any failure.
    """
    tmp_path = None
    try:
        resp = requests.get(pdf_url, timeout=120, headers={"User-Agent": "scibot/1.0"})
        resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        from app.sources.pdf import parse_pdf_local
        text = parse_pdf_local(tmp_path)
        if text and len(text.strip()) > 200:
            return text
    except Exception as exc:
        logger.debug("ArXiv PDF download/parse failed for %s: %s", pdf_url, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

class ArxivSource:
    """Source adapter for arXiv papers."""

    def __init__(self) -> None:
        self._s2 = SemanticScholarClient()

    def fetch(
        self,
        url: str,
        top_n: int = 0,
        depth: int = 0,
    ) -> FetchResult:
        """
        Fetch an arXiv paper, optionally with its top references.

        Parameters
        ----------
        url     : arXiv URL or ID string
        top_n   : number of references to return (ranked globally by citation_count).
                  0 = skip reference fetching entirely.
        depth   : recursion depth (1 = direct refs, 2 = refs of refs, …).
                  0 = skip reference fetching entirely.

        Returns
        -------
        FetchResult with:
          primary    - the requested paper
          references - list of Documents sorted by citation_count desc,
                       each carrying `referenced_by`, `depth`, `citation_count`
                       (empty list when top_n=0 or depth=0)
        """
        arxiv_id = _parse_arxiv_id(url)
        primary = _fetch_paper(arxiv_id, s2_client=self._s2)

        if top_n == 0 or depth == 0:
            return FetchResult(primary=primary, references=[])

        visited: set[str] = {arxiv_id}
        ref_nodes: dict[str, RefNode] = collect_references_arxiv(
            arxiv_id, depth, visited, self._s2
        )

        # Global rank: sort all collected papers by citation_count descending
        ranked = sorted(ref_nodes.items(), key=lambda kv: kv[1]["citation_count"], reverse=True)
        top_ids = [arxiv_id_ for arxiv_id_, _ in ranked[:top_n]]

        references: list[Document] = []
        for ref_id in top_ids:
            try:
                doc = _fetch_paper(ref_id, s2_client=self._s2)
            except Exception as exc:
                logger.debug("Skipping reference paper %s — fetch failed: %s", ref_id, exc)
                continue
            node = ref_nodes[ref_id]
            doc.metadata["referenced_by"] = node["referenced_by"]
            doc.metadata["depth"] = node["depth"]
            doc.metadata["citation_count"] = node["citation_count"]
            references.append(doc)

        return FetchResult(primary=primary, references=references)
