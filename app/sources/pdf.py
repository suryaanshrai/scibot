"""
PDF source adapter.

Supports:
  fetch(path)                                              -> Document
  fetch_with_references(path, top_n, depth, llm_config)   -> FetchResult

`path` must be a local file path to a PDF. All parsing is done entirely locally
by Docling — no API calls are made for content extraction.

Large-file / OCR-failure strategy (see `parse_pdf_local`):
  - Processes the PDF in batches of _PDF_CHUNK_PAGES pages.
  - On OOM / bad_alloc each chunk is retried at reduced image scale.
  - If an entire chunk still fails, individual pages are attempted so that
    at most one bad page is lost rather than the whole document.

Reference extraction pipeline:
  1. parse_pdf_local converts the PDF to Markdown text
  2. An LLM extracts structured references from the text
  3. Semantic Scholar resolves each reference title to an arXiv or PubMed ID
  4. ArxivSource / PubmedSource recursively fetch deeper refs (depth > 1)
  5. All collected papers are globally ranked by citation_count; top N returned
"""

from __future__ import annotations

import json
import re

from langchain_core.documents import Document

from app.config import get_llm
from app.sources.base import (
    FetchResult,
    PaperMetadata,
    RefNode,
    SemanticScholarClient,
    iCiteClient,
    make_document,
)

_REF_EXTRACTION_PROMPT = """\
You are a scientific reference extractor. Given the following text from an academic paper, \
extract all bibliographic references found in the reference list or bibliography section.

For each reference output a JSON array where each element is an object with:
  - "title": the paper title (string)
  - "year": publication year as integer, or null if unknown
  - "authors": first author's last name (string), or null if unknown

Output ONLY the JSON array, no other text.

TEXT:
{text}
"""


# Pages processed in a single Docling pass. Keeps peak memory bounded.
_PDF_CHUNK_PAGES = 10
# Image scales tried on each chunk before giving up (1.0 = full res, 0.5 = half res).
_PDF_SCALES = (1.0, 0.5)


def _run_docling(path: str, start: int, end: int, images_scale: float) -> str | None:
    """
    Run Docling's DocumentConverter on pages [start, end] (1-based, inclusive)
    at the given image scale and return the exported Markdown.  Returns None on
    any failure so the caller can try a different strategy.
    """
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        opts = PdfPipelineOptions()
        opts.images_scale = images_scale

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
        result = converter.convert(path, page_range=(start, end))
        return result.document.export_to_markdown()
    except Exception:
        return None


def parse_pdf_local(path: str) -> str:
    """
    Parse a local PDF file to Markdown text.

    Strategy for large files and OCR memory errors (std::bad_alloc):
      1. Split the document into batches of _PDF_CHUNK_PAGES pages.
      2. For each batch try full image scale first, then half scale on failure.
      3. If the whole batch still fails, fall back to page-by-page at half scale
         so at most individual pages are lost rather than the whole document.

    Docling runs entirely locally — no network calls are made.
    """
    import fitz  # PyMuPDF — already a dependency; used only for cheap page count

    with fitz.open(path) as doc:
        num_pages = doc.page_count

    parts: list[str] = []
    start = 1
    while start <= num_pages:
        end = min(start + _PDF_CHUNK_PAGES - 1, num_pages)
        text: str | None = None

        # Try the full chunk at decreasing resolutions
        for scale in _PDF_SCALES:
            text = _run_docling(path, start, end, scale)
            if text is not None:
                break

        # Chunk failed entirely — fall back to page-by-page at lowest scale
        if text is None:
            page_texts: list[str] = []
            for p in range(start, end + 1):
                t = _run_docling(path, p, p, _PDF_SCALES[-1])
                if t:
                    page_texts.append(t)
            if page_texts:
                text = "\n\n".join(page_texts)

        if text:
            parts.append(text)
        start = end + 1

    return "\n\n".join(parts)


# Keep an internal alias so the rest of this module can use the short name.
_parse_pdf = parse_pdf_local

def _extract_references_with_llm(content: str, llm) -> list[dict]:
    """
    Use an LLM to extract references from PDF text.
    Returns a list of dicts with keys: title, year, authors.
    """
    # Focus on the latter portion of the document where references usually appear
    # Use last ~8000 chars to stay within context limits while capturing the ref section
    excerpt = content[-8000:] if len(content) > 8000 else content
    prompt = _REF_EXTRACTION_PROMPT.format(text=excerpt)

    try:
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        # Strip markdown code fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip(), flags=re.MULTILINE)
        raw = re.sub(r"\n?```$", "", raw.strip(), flags=re.MULTILINE)
        refs = json.loads(raw.strip())
        if isinstance(refs, list):
            return refs
    except Exception:
        pass
    return []


def _resolve_reference(
    ref: dict,
    s2_client: SemanticScholarClient,
) -> tuple[str, str] | None:
    """
    Resolve a reference dict (title, year, authors) to a (source_type, id) pair
    via Semantic Scholar title search.

    Returns ("arxiv", arxiv_id) | ("pubmed", pmid) | None
    """
    title = (ref.get("title") or "").strip()
    if not title:
        return None

    query = title
    year = ref.get("year")
    if year:
        query = f"{title} {year}"

    paper = s2_client.search_paper(query)
    if not paper:
        return None

    ext_ids = paper.get("externalIds") or {}
    arxiv_id = ext_ids.get("ArXiv")
    if arxiv_id:
        return ("arxiv", arxiv_id)

    pmid = ext_ids.get("PubMed")
    if pmid:
        return ("pubmed", str(pmid))

    return None


def _build_ref_nodes_from_resolved(
    resolved: list[tuple[str, str]],  # list of (source_type, id)
    s2_client: SemanticScholarClient,
    icite_client: iCiteClient,
    primary_id: str,
    depth: int,
    visited: set[str],
) -> dict[str, RefNode]:
    """
    Build the initial RefNode dict (depth=1) for directly resolved references,
    then recursively expand if depth > 1.
    """
    from app.sources.base import collect_references_arxiv, collect_references_pubmed

    collected: dict[str, RefNode] = {}

    for source_type, ref_id in resolved:
        if ref_id in visited:
            if ref_id in collected:
                if primary_id not in collected[ref_id]["referenced_by"]:
                    collected[ref_id]["referenced_by"].append(primary_id)
            else:
                collected[ref_id] = RefNode(
                    citation_count=0, referenced_by=[primary_id], depth=1
                )
            continue

        visited.add(ref_id)

        # Get citation count
        citation_count = 0
        if source_type == "arxiv":
            s2_data = s2_client.get_paper_by_arxiv(ref_id)
            if s2_data:
                citation_count = s2_data.get("citationCount") or 0
        else:
            icite_data = icite_client.get_paper(ref_id)
            if icite_data:
                citation_count = icite_data.get("citation_count") or 0

        collected[ref_id] = RefNode(
            citation_count=citation_count, referenced_by=[primary_id], depth=1
        )

        # Recurse deeper if needed
        if depth > 1:
            if source_type == "arxiv":
                sub = collect_references_arxiv(ref_id, depth - 1, visited, s2_client)
            else:
                sub = collect_references_pubmed(ref_id, depth - 1, visited, icite_client)

            for sub_id, sub_node in sub.items():
                # Adjust depth relative to primary (sub_node depths are relative to ref_id)
                adjusted_depth = sub_node["depth"] + 1
                if sub_id in collected:
                    existing = collected[sub_id]
                    existing["depth"] = min(existing["depth"], adjusted_depth)
                    for parent in sub_node["referenced_by"]:
                        if parent not in existing["referenced_by"]:
                            existing["referenced_by"].append(parent)
                else:
                    collected[sub_id] = RefNode(
                        citation_count=sub_node["citation_count"],
                        referenced_by=sub_node["referenced_by"],
                        depth=adjusted_depth,
                    )

    return collected


# ── Public API ────────────────────────────────────────────────────────────────

class PDFSource:
    """Source adapter for local PDF files."""

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
        Parse a PDF, optionally extracting and recursively fetching its references.

        Parameters
        ----------
        path       : local PDF file path
        top_n      : number of references to return (ranked globally by citation_count).
                     0 = skip reference fetching entirely.
        depth      : recursion depth (1 = direct refs, 2 = refs of refs, …).
                     0 = skip reference fetching entirely.
        llm_config : optional LLM config dict passed to get_llm(); uses env defaults if None

        Returns
        -------
        FetchResult with:
          primary    - the parsed PDF as a Document
          references - list of Documents sorted by citation_count desc,
                       each carrying `referenced_by`, `depth`, `citation_count`
                       (empty list when top_n=0 or depth=0)
        """
        content = _parse_pdf(path)
        primary = make_document(
            content,
            {"source_url": path, "paper_type": "pdf", "content_type": "full_text"},
        )

        if top_n == 0 or depth == 0:
            return FetchResult(primary=primary, references=[])

        llm = get_llm(llm_config)
        raw_refs = _extract_references_with_llm(content, llm)

        resolved: list[tuple[str, str]] = []
        for ref in raw_refs:
            result = _resolve_reference(ref, self._s2)
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
            # Determine source type from context: arxiv IDs contain a dot
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
