"""
LaTeX source adapter.

Supports:
  fetch(path)                                              -> Document
  fetch_with_references(path, top_n, depth, llm_config)   -> FetchResult

`path` must be a local .tex file path. Content is parsed via DoclingLoader
(langchain-docling), which natively understands LaTeX structure.

Reference extraction pipeline (in order of priority):
  1. Parse adjacent .bib file(s) for BibTeX `title` fields
  2. Parse \\bibitem entries within the .tex file itself
  3. LLM extraction as fallback when the above yield is poor
  4. Semantic Scholar resolves each title to an arXiv or PubMed ID
  5. ArxivSource / PubmedSource recursively fetch deeper refs (depth > 1)
"""

from __future__ import annotations

import re
from pathlib import Path

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

# ── LaTeX parsing ─────────────────────────────────────────────────────────────

# Matches most common LaTeX commands: \command or \command{...}
_LATEX_COMMAND_RE = re.compile(r"\\[a-zA-Z]+\*?\s*(?:\{[^}]*\})*")
# Inline math
_MATH_RE = re.compile(r"\$[^$]*\$|\$\$[^$]*\$\$")


def _strip_latex(text: str) -> str:
    """Remove common LaTeX markup to produce readable plain text."""
    text = _MATH_RE.sub(" ", text)
    text = _LATEX_COMMAND_RE.sub(" ", text)
    # Remove remaining braces
    text = re.sub(r"[{}]", "", text)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_latex(path: str) -> str:
    """Read a .tex file and return stripped plain text."""
    content = Path(path).read_text(encoding="utf-8", errors="ignore")
    return _strip_latex(content)


def _parse_latex_raw(path: str) -> str:
    """Read raw .tex file content (without stripping, for bib extraction)."""
    return Path(path).read_text(encoding="utf-8", errors="ignore")


# ── Bibliography extraction ───────────────────────────────────────────────────

def _extract_bibitem_titles(tex_content: str) -> list[str]:
    r"""
    Extract reference titles from \bibitem entries in a .tex file.

    Handles two common patterns:
      \bibitem{key} Author et al., \textit{Title of the Paper}, ...
      \bibitem[label]{key} ...
    """
    titles: list[str] = []

    # Grab everything between \bibitem ... \bibitem (or end of content)
    bibitem_blocks = re.split(r"\\bibitem(?:\[[^\]]*\])?\{[^}]+\}", tex_content)
    # First element is pre-bibliography content
    for block in bibitem_blocks[1:]:
        # Take first sentence / clause as title heuristic
        # Strip internal commands and grab first ~200 chars
        clean = re.sub(r"\\[a-zA-Z]+\*?\s*\{([^}]*)\}", r"\1", block)
        clean = re.sub(r"[\\{}]", "", clean).strip()
        # Split on common separators (comma before year, period)
        parts = re.split(r"\.\s+|\,\s+\d{4}", clean)
        candidate = parts[0].strip() if parts else clean[:200].strip()
        if len(candidate) > 10:
            titles.append(candidate)

    return titles


_BIB_TITLE_RE = re.compile(r"title\s*=\s*[{\"](.+?)[}\"]", re.IGNORECASE | re.DOTALL)


def _extract_bib_file_titles(tex_path: str) -> list[str]:
    """
    Look for .bib files in the same directory as the .tex file and
    extract title fields from all BibTeX entries.
    """
    tex_dir = Path(tex_path).parent
    titles: list[str] = []
    for bib_file in tex_dir.glob("*.bib"):
        content = bib_file.read_text(encoding="utf-8", errors="ignore")
        for m in _BIB_TITLE_RE.finditer(content):
            title = re.sub(r"\s+", " ", m.group(1)).strip()
            if title:
                titles.append(title)
    return titles


def _extract_bib_entries(tex_path: str) -> list[str]:
    """
    Collect reference titles from all available sources:
      1. Adjacent .bib file(s)
      2. \\bibitem entries in the .tex itself

    Returns a deduplicated list of title strings.
    """
    raw = _parse_latex_raw(tex_path)

    titles: list[str] = []
    titles.extend(_extract_bib_file_titles(tex_path))
    titles.extend(_extract_bibitem_titles(raw))

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in titles:
        key = t.lower().strip()
        if key not in seen and len(key) > 5:
            seen.add(key)
            unique.append(t)

    return unique


# ── Public API ────────────────────────────────────────────────────────────────

class LatexSource:
    """Source adapter for LaTeX (.tex) files."""

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
        Parse a .tex file, optionally extracting and recursively fetching its references.

        Parameters
        ----------
        path       : local .tex file path
        top_n      : number of references to return (ranked globally by citation_count).
                     0 = skip reference fetching entirely.
        depth      : recursion depth (1 = direct refs, 2 = refs of refs, …).
                     0 = skip reference fetching entirely.
        llm_config : optional LLM config dict passed to get_llm(); uses env defaults if None

        Returns
        -------
        FetchResult with:
          primary    - the parsed .tex as a Document
          references - list of Documents sorted by citation_count desc,
                       each carrying `referenced_by`, `depth`, `citation_count`
                       (empty list when top_n=0 or depth=0)
        """
        content = _parse_latex(path)
        primary = make_document(
            content,
            {"source_url": path, "paper_type": "latex", "content_type": "full_text"},
        )

        if top_n == 0 or depth == 0:
            return FetchResult(primary=primary, references=[])

        # Phase 1: structured extraction from .bib / \bibitem
        titles = _extract_bib_entries(path)

        # Phase 2: LLM fallback if structured extraction yield is poor
        if len(titles) < 3:
            llm = get_llm(llm_config)
            llm_refs = _llm_extract(content, llm)
            llm_titles = [r.get("title", "") for r in llm_refs if r.get("title")]
            # Merge, dedup
            existing_lower = {t.lower() for t in titles}
            for t in llm_titles:
                if t.lower() not in existing_lower:
                    titles.append(t)
                    existing_lower.add(t.lower())

        # Resolve to arXiv / PubMed IDs via S2
        resolved: list[tuple[str, str]] = []
        for title in titles:
            result = _resolve_reference({"title": title}, self._s2)
            if result:
                resolved.append(result)

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
