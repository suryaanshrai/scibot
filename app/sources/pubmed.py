"""
PubMed source adapter.

Supports:
  fetch(url)                                  -> Document
  fetch_with_references(url, top_n, depth)    -> FetchResult

URL/ID formats accepted:
  https://pubmed.ncbi.nlm.nih.gov/41812192/
  https://www.ncbi.nlm.nih.gov/pubmed/41812192
  41812192    (bare PMID)
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

import requests
from langchain_core.documents import Document

from app.config.settings import NCBI_API_KEY
from app.sources.base import (
    FetchResult,
    RefNode,
    iCiteClient,
    collect_references_pubmed,
    make_document,
)

_PMID_RE = re.compile(r"(?:pubmed(?:\.ncbi\.nlm\.nih\.gov)?/|pubmed/)(\d+)", re.IGNORECASE)
_BARE_PMID_RE = re.compile(r"^\d+$")

_NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_NCBI_DELAY = 0.12 if NCBI_API_KEY else 0.35  # 10/s with key, 3/s without


def _parse_pmid(url: str) -> str:
    """Extract a normalised PMID string from any supported URL/string."""
    url = url.strip()
    m = _PMID_RE.search(url)
    if m:
        return m.group(1)
    if _BARE_PMID_RE.match(url):
        return url
    raise ValueError(f"Cannot parse PMID from: {url!r}")


def _ncbi_params(extra: dict | None = None) -> dict:
    """Base NCBI eUtils params, including optional API key."""
    p: dict = {"tool": "scibot", "email": "scibot@example.com"}
    if NCBI_API_KEY:
        p["api_key"] = NCBI_API_KEY
    if extra:
        p.update(extra)
    return p


def _load_pubmed_abstract(pmid: str) -> tuple[str, dict]:
    """
    Fetch title, abstract and basic metadata via NCBI EFetch (direct ID lookup).
    Using EFetch rather than PubMedLoader because PubMedLoader uses a text-search
    query internally and may miss papers by PMID.
    Returns (abstract_text, metadata_dict).
    """
    time.sleep(_NCBI_DELAY)
    resp = requests.get(
        f"{_NCBI_BASE}/efetch.fcgi",
        params=_ncbi_params({"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"}),
        timeout=20,
    )
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    article = root.find(".//PubmedArticle")
    if article is None:
        raise ValueError(f"No PubMed result found for PMID: {pmid}")

    title = "".join((article.findtext(".//ArticleTitle") or "").split())
    # Re-join with spaces (itertext sometimes drops them)
    title_el = article.find(".//ArticleTitle")
    title = "".join(title_el.itertext()).strip() if title_el is not None else ""

    abstract_parts = [
        "".join(el.itertext()).strip()
        for el in article.findall(".//AbstractText")
    ]
    abstract = "\n\n".join(p for p in abstract_parts if p)

    year_el = (
        article.find(".//PubDate/Year")
        or article.find(".//DateCompleted/Year")
        or article.find(".//DateRevised/Year")
    )
    year = int(year_el.text) if year_el is not None and year_el.text else None

    authors: list[str] = []
    for author in article.findall(".//Author"):
        last = author.findtext("LastName") or ""
        fore = author.findtext("ForeName") or author.findtext("Initials") or ""
        name = f"{fore} {last}".strip()
        if name:
            authors.append(name)

    metadata = {
        "pmid": pmid,
        "title": title,
        "authors": authors,
        "year": year,
        "abstract": abstract,
        "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "paper_type": "pubmed",
    }
    return abstract, metadata


def _fetch_pmc_fulltext(pmid: str) -> str | None:
    """
    Attempt to fetch full text from PMC for a given PMID.

    Steps:
      1. ELink: PMID → PMCID
      2. EFetch PMC XML → extract body text

    Returns None if the paper is not available in PMC.
    """
    # Step 1: ELink to get PMCID
    time.sleep(_NCBI_DELAY)
    elink_resp = requests.get(
        f"{_NCBI_BASE}/elink.fcgi",
        params=_ncbi_params(
            {"dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "xml"}
        ),
        timeout=20,
    )
    if elink_resp.status_code != 200:
        return None

    elink_root = ET.fromstring(elink_resp.content)
    pmcid_el = elink_root.find(".//LinkSetDb/Link/Id")
    if pmcid_el is None or not pmcid_el.text:
        return None

    pmcid = pmcid_el.text.strip()

    # Step 2: EFetch full text from PMC
    time.sleep(_NCBI_DELAY)
    efetch_resp = requests.get(
        f"{_NCBI_BASE}/efetch.fcgi",
        params=_ncbi_params({"db": "pmc", "id": pmcid, "retmode": "xml"}),
        timeout=30,
    )
    if efetch_resp.status_code != 200:
        return None

    pmc_root = ET.fromstring(efetch_resp.content)

    # Collect all body text nodes
    paragraphs: list[str] = []
    for p_el in pmc_root.findall(".//body//p"):
        text = "".join(p_el.itertext()).strip()
        if text:
            paragraphs.append(text)

    if not paragraphs:
        return None

    return "\n\n".join(paragraphs)


def _fetch_paper(pmid: str, citation_count: int = 0) -> Document:
    """
    Fetch a PubMed paper; prefer PMC full text, fall back to abstract.
    """
    abstract, metadata = _load_pubmed_abstract(pmid)
    metadata["citation_count"] = citation_count

    full_text = _fetch_pmc_fulltext(pmid)
    if full_text and len(full_text.strip()) > len(abstract):
        metadata["content_type"] = "full_text"
        return make_document(full_text, metadata)

    metadata["content_type"] = "abstract"
    return make_document(abstract, metadata)


# ── Public API ────────────────────────────────────────────────────────────────

class PubmedSource:
    """Source adapter for PubMed papers."""

    def __init__(self) -> None:
        self._icite = iCiteClient()

    def fetch(
        self,
        url: str,
        top_n: int = 0,
        depth: int = 0,
    ) -> FetchResult:
        """
        Fetch a PubMed paper, optionally with its top references.

        Parameters
        ----------
        url     : PubMed URL or bare PMID
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
        pmid = _parse_pmid(url)

        icite_data = self._icite.get_paper(pmid)
        primary_citation_count = (icite_data.get("citation_count") or 0) if icite_data else 0
        primary = _fetch_paper(pmid, citation_count=primary_citation_count)

        if top_n == 0 or depth == 0:
            return FetchResult(primary=primary, references=[])

        visited: set[str] = {pmid}
        ref_nodes: dict[str, RefNode] = collect_references_pubmed(
            pmid, depth, visited, self._icite
        )

        # Global rank by citation_count descending
        ranked = sorted(ref_nodes.items(), key=lambda kv: kv[1]["citation_count"], reverse=True)
        top_ids = [pmid_ for pmid_, _ in ranked[:top_n]]

        references: list[Document] = []
        for ref_pmid in top_ids:
            node = ref_nodes[ref_pmid]
            try:
                doc = _fetch_paper(ref_pmid, citation_count=node["citation_count"])
            except Exception:
                continue
            doc.metadata["referenced_by"] = node["referenced_by"]
            doc.metadata["depth"] = node["depth"]
            doc.metadata["citation_count"] = node["citation_count"]
            references.append(doc)

        return FetchResult(primary=primary, references=references)
