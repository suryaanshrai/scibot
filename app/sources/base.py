"""
Shared utilities for all source adapters.

Provides:
  - PaperMetadata / RefNode / FetchResult TypedDicts
  - SemanticScholarClient  (arXiv reference graph via S2 API)
  - iCiteClient            (PubMed reference graph via NIH iCite API)
  - collect_references_arxiv / collect_references_pubmed
  - make_document helper
"""

from __future__ import annotations

import time
from typing import Any, TypedDict

import requests
from langchain_core.documents import Document

from app.config.settings import NCBI_API_KEY, SEMANTIC_SCHOLAR_API_KEY


# ── TypedDicts ────────────────────────────────────────────────────────────────

class PaperMetadata(TypedDict, total=False):
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    arxiv_id: str
    pmid: str
    doi: str
    citation_count: int
    source_url: str
    paper_type: str          # "arxiv" | "pubmed" | "pdf" | "latex" | "markdown"
    content_type: str        # "full_text" | "abstract"


class RefNode(TypedDict):
    citation_count: int
    referenced_by: list[str]   # IDs of papers that directly cite this one (within the traversal)
    depth: int                  # minimum depth from the primary paper


class FetchResult(TypedDict):
    primary: Document
    references: list[Document]  # sorted by citation_count desc; len = min(top_n, found)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_document(content: str, metadata: dict[str, Any]) -> Document:
    return Document(page_content=content, metadata=metadata)


# ── Semantic Scholar client ───────────────────────────────────────────────────

_S2_BASE = "https://api.semanticscholar.org/graph/v1"
_S2_FIELDS = "title,year,authors,abstract,externalIds,citationCount"
_S2_REF_FIELDS = "citedPaper.title,citedPaper.year,citedPaper.externalIds,citedPaper.citationCount"


class SemanticScholarClient:
    """
    Thin wrapper around the Semantic Scholar Graph API.

    Rate limits:
      - Anonymous : ~1 req/s
      - With key  : ~100 req/s
    """

    def __init__(self) -> None:
        self._key = SEMANTIC_SCHOLAR_API_KEY
        self._delay = 0.1 if self._key else 1.05

    def _headers(self) -> dict[str, str]:
        if self._key:
            return {"x-api-key": self._key}
        return {}

    def _get(self, url: str, params: dict | None = None) -> dict | None:
        time.sleep(self._delay)
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                # Back off and retry once
                time.sleep(5)
                resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
        except requests.RequestException:
            pass
        return None

    def get_paper_by_arxiv(self, arxiv_id: str) -> dict | None:
        """Return S2 paper record for an arXiv ID."""
        data = self._get(f"{_S2_BASE}/paper/arXiv:{arxiv_id}", params={"fields": _S2_FIELDS})
        return data

    def get_paper_by_pmid(self, pmid: str) -> dict | None:
        """Return S2 paper record for a PubMed ID."""
        data = self._get(f"{_S2_BASE}/paper/PMID:{pmid}", params={"fields": _S2_FIELDS})
        return data

    def get_references(self, s2_paper_id: str) -> list[dict]:
        """
        Return cited-paper records for an S2 paperId.
        Each item has: citedPaper.{title, year, externalIds, citationCount}
        """
        data = self._get(
            f"{_S2_BASE}/paper/{s2_paper_id}/references",
            params={"fields": _S2_REF_FIELDS, "limit": 100},
        )
        if data and "data" in data:
            return data["data"]
        return []

    def search_paper(self, query: str) -> dict | None:
        """
        Search by title/keyword; returns the best-matching paper record or None.
        """
        data = self._get(
            f"{_S2_BASE}/paper/search",
            params={"query": query, "fields": _S2_FIELDS, "limit": 1},
        )
        if data and data.get("data"):
            return data["data"][0]
        return None


# ── iCite client ──────────────────────────────────────────────────────────────

_ICITE_BASE = "https://icite.od.nih.gov/api/pubs"


class iCiteClient:
    """
    Thin wrapper around the NIH iCite API for PubMed citation data.
    No authentication required; practical limit ~10 req/s.
    """

    def __init__(self) -> None:
        self._delay = 0.15

    def _get(self, params: dict) -> dict | None:
        time.sleep(self._delay)
        try:
            resp = requests.get(_ICITE_BASE, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def get_paper(self, pmid: str | int) -> dict | None:
        """Return iCite record for a single PMID."""
        data = self._get({"pmids": str(pmid)})
        if data and data.get("data"):
            return data["data"][0]
        return None

    def get_papers_batch(self, pmids: list[str | int]) -> list[dict]:
        """Return iCite records for a batch of PMIDs (max 100 per call)."""
        if not pmids:
            return []
        results: list[dict] = []
        # iCite supports comma-separated PMIDs
        for i in range(0, len(pmids), 100):
            chunk = pmids[i : i + 100]
            data = self._get({"pmids": ",".join(str(p) for p in chunk)})
            if data and data.get("data"):
                results.extend(data["data"])
        return results


# ── Recursive reference collectors ───────────────────────────────────────────

def collect_references_arxiv(
    arxiv_id: str,
    depth: int,
    visited: set[str],
    s2_client: SemanticScholarClient,
    _parent_id: str | None = None,
    _current_depth: int = 1,
) -> dict[str, RefNode]:
    """
    Recursively collect arXiv references up to `depth` levels deep.

    Returns a dict mapping arxiv_id → RefNode.
    When the same paper is reachable via multiple paths:
      - `referenced_by` accumulates all parent IDs
      - `depth` keeps the minimum distance
    """
    if _current_depth > depth:
        return {}

    paper_data = s2_client.get_paper_by_arxiv(arxiv_id)
    if paper_data is None:
        return {}

    s2_id = paper_data.get("paperId")
    if not s2_id:
        return {}

    references = s2_client.get_references(s2_id)
    collected: dict[str, RefNode] = {}

    for ref in references:
        cited = ref.get("citedPaper", {})
        ext_ids = cited.get("externalIds") or {}
        ref_arxiv_id = ext_ids.get("ArXiv")
        if not ref_arxiv_id:
            continue

        citation_count = cited.get("citationCount") or 0

        if ref_arxiv_id in collected:
            # Already seen in this subtree — update min depth and add parent
            node = collected[ref_arxiv_id]
            node["depth"] = min(node["depth"], _current_depth)
            if arxiv_id not in node["referenced_by"]:
                node["referenced_by"].append(arxiv_id)
        elif ref_arxiv_id in visited:
            # Already processed globally — just record provenance
            collected[ref_arxiv_id] = RefNode(
                citation_count=citation_count,
                referenced_by=[arxiv_id],
                depth=_current_depth,
            )
        else:
            visited.add(ref_arxiv_id)
            collected[ref_arxiv_id] = RefNode(
                citation_count=citation_count,
                referenced_by=[arxiv_id],
                depth=_current_depth,
            )

            # Recurse deeper
            if _current_depth < depth:
                sub = collect_references_arxiv(
                    ref_arxiv_id,
                    depth,
                    visited,
                    s2_client,
                    _parent_id=ref_arxiv_id,
                    _current_depth=_current_depth + 1,
                )
                for sub_id, sub_node in sub.items():
                    if sub_id in collected:
                        existing = collected[sub_id]
                        existing["depth"] = min(existing["depth"], sub_node["depth"])
                        for parent in sub_node["referenced_by"]:
                            if parent not in existing["referenced_by"]:
                                existing["referenced_by"].append(parent)
                    else:
                        collected[sub_id] = sub_node

    return collected


def collect_references_pubmed(
    pmid: str,
    depth: int,
    visited: set[str],
    icite_client: iCiteClient,
    _current_depth: int = 1,
) -> dict[str, RefNode]:
    """
    Recursively collect PubMed references up to `depth` levels deep via iCite.

    Returns a dict mapping pmid (str) → RefNode.
    """
    if _current_depth > depth:
        return {}

    paper_data = icite_client.get_paper(pmid)
    if paper_data is None:
        return {}

    # iCite returns references as a list of PMIDs
    ref_pmids: list[int] = paper_data.get("references") or []
    if not ref_pmids:
        return {}

    # Fetch citation counts for all referenced PMIDs in one batch call
    ref_pmid_strs = [str(p) for p in ref_pmids]
    batch = icite_client.get_papers_batch(ref_pmid_strs)
    batch_map = {str(r["pmid"]): r for r in batch if r.get("pmid")}

    collected: dict[str, RefNode] = {}

    for ref_pmid_str in ref_pmid_strs:
        ref_data = batch_map.get(ref_pmid_str, {})
        citation_count = ref_data.get("citation_count") or 0

        if ref_pmid_str in collected:
            node = collected[ref_pmid_str]
            node["depth"] = min(node["depth"], _current_depth)
            if pmid not in node["referenced_by"]:
                node["referenced_by"].append(pmid)
        elif ref_pmid_str in visited:
            collected[ref_pmid_str] = RefNode(
                citation_count=citation_count,
                referenced_by=[pmid],
                depth=_current_depth,
            )
        else:
            visited.add(ref_pmid_str)
            collected[ref_pmid_str] = RefNode(
                citation_count=citation_count,
                referenced_by=[pmid],
                depth=_current_depth,
            )

            if _current_depth < depth:
                sub = collect_references_pubmed(
                    ref_pmid_str,
                    depth,
                    visited,
                    icite_client,
                    _current_depth=_current_depth + 1,
                )
                for sub_id, sub_node in sub.items():
                    if sub_id in collected:
                        existing = collected[sub_id]
                        existing["depth"] = min(existing["depth"], sub_node["depth"])
                        for parent in sub_node["referenced_by"]:
                            if parent not in existing["referenced_by"]:
                                existing["referenced_by"].append(parent)
                    else:
                        collected[sub_id] = sub_node

    return collected
