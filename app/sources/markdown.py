"""
Markdown source adapter.

Supports:
  fetch(path)                                              -> Document
  fetch_with_references(path, top_n, depth, llm_config)   -> FetchResult

`path` must be a local .md file path.

Reference extraction pipeline (in order of priority):
  1. Regex extraction of bare arXiv IDs, PubMed URLs, DOIs, and markdown links
  2. LLM extraction as complement / fallback for natural-language ref lists
  3. Semantic Scholar resolves each title/DOI/ID to an arXiv or PubMed record
  4. ArxivSource / PubmedSource recursively fetch deeper refs (depth > 1)
"""

from __future__ import annotations

import re
from langchain_core.documents import Document

from app.config import get_llm
from app.sources.base import (
    FetchResult,
    RefNode,
    SemanticScholarClient,
    iCiteClient,
    make_document,
)
from app.sources.pdf import (
    _build_ref_nodes_from_resolved,
    _extract_references_with_llm as _llm_extract,
    _resolve_reference,
)

# ── Regex patterns for common scientific identifiers ─────────────────────────

# arXiv IDs: 1706.03762, arxiv:1706.03762, arxiv.org/abs/1706.03762
_ARXIV_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:)"
    r"([a-z\-]+/\d{7}|\d{4}\.\d{4,5})"
    r"(?:v\d+)?",
    re.IGNORECASE,
)
# Bare new-style arXiv IDs in text (e.g. "as shown in [1706.03762]")
_ARXIV_BARE_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")

# PubMed URLs
_PUBMED_RE = re.compile(
    r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|ncbi\.nlm\.nih\.gov/pubmed/)(\d+)",
    re.IGNORECASE,
)

# DOIs — capture the raw DOI string for S2 lookup
_DOI_RE = re.compile(r"\b(10\.\d{4,}/\S+?)(?=[)\]\s,]|$)", re.IGNORECASE)

# Markdown link targets: [text](url)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")


def _parse_markdown(path: str) -> str:
    """
    Convert a Markdown file via DoclingLoader (langchain-docling).
    Docling normalizes structure while preserving all link targets,
    arXiv/DOI/PubMed references, and bibliography patterns needed for
    downstream regex and LLM extraction.
    """
    from langchain_docling import DoclingLoader
    from langchain_docling.loader import ExportType

    loader = DoclingLoader(file_path=path, export_type=ExportType.MARKDOWN)
    docs = loader.load()
    return "\n\n".join(d.page_content for d in docs)


def _extract_references_regex(content: str) -> list[tuple[str, str]]:
    """
    Extract arXiv and PubMed identifiers directly from Markdown content via regex.

    Returns a list of (source_type, id) tuples:
      ("arxiv", arxiv_id) | ("pubmed", pmid)
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(source_type: str, id_: str) -> None:
        key = f"{source_type}:{id_}"
        if key not in seen:
            seen.add(key)
            found.append((source_type, id_))

    # arXiv from explicit URLs / prefixes
    for m in _ARXIV_RE.finditer(content):
        _add("arxiv", m.group(1))

    # Bare arXiv IDs
    for m in _ARXIV_BARE_RE.finditer(content):
        _add("arxiv", m.group(1))

    # PubMed URLs
    for m in _PUBMED_RE.finditer(content):
        _add("pubmed", m.group(1))

    return found


def _extract_doi_queries(content: str) -> list[str]:
    """Extract DOI strings from Markdown content for S2 title search."""
    return [m.group(1) for m in _DOI_RE.finditer(content)]


# ── Public API ────────────────────────────────────────────────────────────────

class MarkdownSource:
    """Source adapter for Markdown (.md) files."""

    def __init__(self) -> None:
        self._s2 = SemanticScholarClient()
        self._icite = iCiteClient()

    def fetch(
        self,
        path: str,
        top_n: int = 0,
        depth: int = 0,
        llm_config: dict | None = None,
    ) -> FetchResult:
        """
        Parse a Markdown file, optionally extracting and recursively fetching its references.

        Parameters
        ----------
        path       : local .md file path
        top_n      : number of references to return (ranked globally by citation_count).
                     0 = skip reference fetching entirely.
        depth      : recursion depth (1 = direct refs, 2 = refs of refs, …).
                     0 = skip reference fetching entirely.
        llm_config : optional LLM config dict passed to get_llm(); uses env defaults if None

        Returns
        -------
        FetchResult with:
          primary    - the Markdown file as a Document
          references - list of Documents sorted by citation_count desc,
                       each carrying `referenced_by`, `depth`, `citation_count`
                       (empty list when top_n=0 or depth=0)
        """
        content = _parse_markdown(path)
        primary = make_document(
            content,
            {"source_url": path, "paper_type": "markdown", "content_type": "full_text"},
        )

        if top_n == 0 or depth == 0:
            return FetchResult(primary=primary, references=[])

        # Phase 1: regex — directly identified arXiv / PubMed IDs
        direct_ids = _extract_references_regex(content)

        # Phase 2: DOI-based S2 lookup
        doi_resolved: list[tuple[str, str]] = []
        for doi in _extract_doi_queries(content):
            paper = self._s2.search_paper(doi)
            if paper:
                ext_ids = paper.get("externalIds") or {}
                arxiv_id = ext_ids.get("ArXiv")
                pmid = ext_ids.get("PubMed")
                if arxiv_id:
                    doi_resolved.append(("arxiv", arxiv_id))
                elif pmid:
                    doi_resolved.append(("pubmed", str(pmid)))

        # Phase 3: LLM extraction for natural-language reference lists
        llm_resolved: list[tuple[str, str]] = []
        llm_refs = _llm_extract(content, get_llm(llm_config))
        for ref in llm_refs:
            result = _resolve_reference(ref, self._s2)
            if result:
                llm_resolved.append(result)

        # Merge all resolved IDs, deduplicated
        seen_ids: set[str] = set()
        resolved: list[tuple[str, str]] = []
        for source_type, ref_id in direct_ids + doi_resolved + llm_resolved:
            key = f"{source_type}:{ref_id}"
            if key not in seen_ids:
                seen_ids.add(key)
                resolved.append((source_type, ref_id))

        visited: set[str] = {path}
        ref_nodes = _build_ref_nodes_from_resolved(
            resolved, self._s2, self._icite, path, depth, visited
        )

        # Global rank by citation_count descending
        ranked = sorted(ref_nodes.items(), key=lambda kv: kv[1]["citation_count"], reverse=True)
        top_items = ranked[:top_n]

        references: list[Document] = []
        for ref_id, node in top_items:
            if re.match(r"\d{4}\.\d{4,5}$", ref_id) or re.match(r"[a-z\-]+/\d{7}$", ref_id):
                source_type = "arxiv"
            elif ref_id.isdigit():
                source_type = "pubmed"
            else:
                continue

            try:
                if source_type == "arxiv":
                    from app.sources.arxiv import _fetch_paper as arxiv_fetch
                    doc = arxiv_fetch(ref_id, s2_client=self._s2)
                else:
                    from app.sources.pubmed import _fetch_paper as pubmed_fetch
                    doc = pubmed_fetch(ref_id, citation_count=node["citation_count"])
            except Exception:
                continue

            doc.metadata["referenced_by"] = node["referenced_by"]
            doc.metadata["depth"] = node["depth"]
            doc.metadata["citation_count"] = node["citation_count"]
            references.append(doc)

        return FetchResult(primary=primary, references=references)
