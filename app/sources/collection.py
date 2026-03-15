"""
Collection source adapter — multi-source aggregator.

A Collection groups data from any combination of the twelve source adapters
into a single named unit.  The structural metadata (which sources were loaded,
paper titles/references, playlist memberships, etc.) is persisted as a JSON
blob in the SQLite database.  The actual LangChain ``Document`` objects are
serialised individually as pickle files on disk so that large corpora can be
processed without exhausting memory.

Document storage layout
-----------------------
    app/data/{username}/{collection_name}/documents/doc_0001.pkl
    app/data/{username}/{collection_name}/documents/doc_0002.pkl
    ...

Each file contains exactly one ``langchain_core.documents.Document`` object.
The sequential numbering allows safe appending via ``update_collection``.

Source-level tracking fields (added to every source entry in DB)
----------------------------------------------------------------
Every source entry now carries three extra fields set by this module:

``source_id``   — stable, human-readable identifier for the source, used by
                  the ingestion layer to target per-source vector operations:
                    papers    → "arxiv:1706.03762" | "pubmed:12345678"
                               | "pdf:/abs/path/file.pdf" | "latex:…" | "markdown:…"
                    youtube   → "youtube:https://youtu.be/…"
                    github    → "github:https://github.com/owner/repo"
                    webpages  → "webpage:https://example.com/article"
                    videos    → "video:/abs/path/lecture.mp4"
                    audios    → "audio:/abs/path/talk.mp3"
                    images    → "image:/abs/path/figure.png"

``doc_paths``   — list of absolute paths to the pickle files for this source,
                  in insertion order.  Allows the ingestion layer to load
                  only the documents for a specific source without scanning
                  the whole directory.

``ingested_at`` — ISO-8601 UTC timestamp set by ``app.storage.ingestion``
                  after the source's vectors are written to the store.
                  ``null`` means the source has not been ingested yet.

Collection data dict (stored in DB)
-------------------------------------
{
    "collection_name": "alice_attention-paper",
    "username":        "alice",
    "created_at":      "2026-03-16T12:00:00Z",
    "updated_at":      "2026-03-16T12:00:00Z",

    "papers": [
        {
            "source_type":      "arxiv",
            "source_id":        "arxiv:1706.03762",
            "source_url":       "https://arxiv.org/abs/1706.03762",
            "title":            "Attention Is All You Need",
            "authors":          ["Vaswani", "..."],
            "year":             2017,
            "fetch_references": true,
            "reference_depth":  2,
            "reference_top_n":  10,
            "doc_paths":        ["/…/doc_0001.pkl"],
            "ingested_at":      null,
            "references": [
                {
                    "id":            "1502.03167",
                    "id_type":       "arxiv_id",
                    "title":         "Batch Normalisation",
                    "depth":         1,
                    "referenced_by": ["1706.03762"],
                    "citation_count": 50000
                }
            ]
        }
    ],

    "youtube": [
        {
            "url":            "https://youtu.be/dQw4w9WgXcQ",
            "source_id":      "youtube:https://youtu.be/dQw4w9WgXcQ",
            "title":          "Rick Astley - Never Gonna Give You Up",
            "is_playlist":    false,
            "playlist_url":   null,
            "author":         "Rick Astley",
            "length_seconds": 213,
            "publish_date":   "2009-10-25",
            "doc_paths":      ["/…/doc_0002.pkl"],
            "ingested_at":    null
        }
    ],

    "github_repos": [
        { "url": "https://github.com/owner/repo", "branch": "main", "file_count": 42 }
    ],

    "webpages": [
        { "url": "https://example.com/article", "crawl": false, "page_count": 1 }
    ],

    "videos":  [ { "file_path": "/path/to/lecture.mp4",  "metadata": { "frame_count": 120 } } ],
    "audios":  [ { "file_path": "/path/to/talk.mp3",     "metadata": { "duration_seconds": 3600, "language": "en", "word_count": 8000, "model_size": "base" } } ],
    "images":  [ { "file_path": "/path/to/figure.png",   "metadata": { "description": "Flow diagram ..." } } ]
}

Public API
----------
create_collection(username, collection_name, sources, config, password) -> CollectionResult
list_collections(username)                                               -> list[dict]
get_collection(username, collection_name)                                -> dict
update_collection(username, collection_name, new_sources, config, password) -> CollectionResult
delete_collection(username, collection_name)                             -> None
reload_collection(username, collection_name, config, password)          -> CollectionResult
"""

from __future__ import annotations

import pickle
import re as _re
import shutil
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Required, TypedDict

from langchain_core.documents import Document

from app.sources.base import resolve_data_dir
from app.sources.dynamic_data import DynamicDataSourceConfig, load_dynamic_source
from app.users.collections_db import (
    delete_collection_record,
    list_collections as _db_list_collections,
    load_collection,
    save_collection,
    update_collection_data,
)


# ── Input TypedDicts ──────────────────────────────────────────────────────────

class PaperSource(TypedDict, total=False):
    """Config for a single academic paper source (arXiv, PubMed, PDF, LaTeX, Markdown)."""
    url_or_path:     Required[str]   # arXiv URL/ID, PubMed URL/PMID, or local file path
    source_type:     str             # "arxiv"|"pubmed"|"pdf"|"latex"|"markdown" — auto-detected if omitted
    fetch_references: bool           # default False
    reference_depth: int             # default 1  (only relevant when fetch_references=True)
    reference_top_n: int             # default 10 (only relevant when fetch_references=True)


class YoutubeSourceConfig(TypedDict, total=False):
    """Config for a YouTube video or playlist."""
    url:      Required[str]
    language: list[str]              # preferred transcript language codes, default ["en"]


class GithubSourceConfig(TypedDict, total=False):
    """Config for a GitHub repository, folder, or single file."""
    url:    Required[str]
    branch: str                      # informational; branch must be embedded in the URL


class WebSourceConfig(TypedDict, total=False):
    """Config for a web page or a recursively crawled website."""
    url:       Required[str]
    crawl:     bool                  # False (default) = single page; True = recursive crawl
    max_depth: int                   # only used when crawl=True, default 2


class VideoSourceConfig(TypedDict, total=False):
    """Config for a local video file."""
    file_path: Required[str]


class AudioSourceConfig(TypedDict, total=False):
    """Config for a local audio file."""
    file_path:  Required[str]
    model_size: str                  # Whisper model size, default "base"


class ImageSourceConfig(TypedDict, total=False):
    """Config for a local image file."""
    file_path:   Required[str]
    description: str                 # optional pre-supplied description (skips LLM describe step)


class CollectionSources(TypedDict, total=False):
    """Full set of sources to include in a collection."""
    papers:          list[PaperSource]
    youtube:         list[YoutubeSourceConfig]
    github:          list[GithubSourceConfig]
    webpages:        list[WebSourceConfig]
    videos:          list[VideoSourceConfig]
    audios:          list[AudioSourceConfig]
    images:          list[ImageSourceConfig]
    dynamic_sources: list[DynamicDataSourceConfig]


class CollectionResult(TypedDict):
    """Return value of create / update / reload operations."""
    collection:      dict        # full collection data dict (as stored in DB)
    collection_name: str
    document_paths:  list[str]  # absolute paths to every pkl file in the collection
    load_errors:     list[str]  # non-fatal per-source error messages


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_ARXIV_BARE_ID = _re.compile(
    r"^(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(v\d+)?$",
    _re.IGNORECASE,
)


def _detect_source_type(url_or_path: str) -> str:
    """Infer the source type from a URL or local file path."""
    s = url_or_path.lower().strip()
    if "arxiv.org" in s or s.startswith("arxiv:") or bool(_ARXIV_BARE_ID.match(s)):
        return "arxiv"
    if (
        "pubmed.ncbi.nlm.nih.gov" in s
        or "ncbi.nlm.nih.gov/pubmed" in s
        or s.isdigit()
    ):
        return "pubmed"
    if "github.com" in s:
        return "github"
    if s.endswith(".pdf"):
        return "pdf"
    if s.endswith(".tex"):
        return "latex"
    if s.endswith(".md"):
        return "markdown"
    if s.startswith("http://") or s.startswith("https://"):
        return "webpage"
    raise ValueError(f"Cannot detect source type for: {url_or_path!r}")


def _docs_dir(username: str, collection_name: str) -> Path:
    """Return (and create) the documents pickle directory for a collection."""
    p = resolve_data_dir(username, collection_name) / "documents"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _pickle_docs(docs: list[Document], docs_dir: Path, start_index: int) -> list[str]:
    """
    Serialise each Document to its own pickle file.

    Files are named ``doc_{n:04d}.pkl`` where *n* starts at ``start_index + 1``.
    Returns absolute path strings for every file written.
    """
    paths: list[str] = []
    for i, doc in enumerate(docs, start=start_index + 1):
        file_path = docs_dir / f"doc_{i:04d}.pkl"
        with open(file_path, "wb") as fh:
            pickle.dump(doc, fh, protocol=pickle.HIGHEST_PROTOCOL)
        paths.append(str(file_path))
    return paths


def _existing_doc_count(docs_dir: Path) -> int:
    """Return the number of ``doc_*.pkl`` files already present."""
    if not docs_dir.exists():
        return 0
    return len(list(docs_dir.glob("doc_*.pkl")))


# ── Source-ID helpers ─────────────────────────────────────────────────────────

_ARXIV_ID_FROM_URL = _re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:)"
    r"([a-z\-]+/\d{7}|\d{4}\.\d{4,5})",
    _re.IGNORECASE,
)
_BARE_ARXIV_RE = _re.compile(
    r"^([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(v\d+)?$",
    _re.IGNORECASE,
)
_PMID_RE = _re.compile(r"(?:pubmed(?:\.ncbi\.nlm\.nih\.gov)?/|pubmed/)(\d+)", _re.IGNORECASE)


def _source_id_for_paper(stype: str, url_or_path: str) -> str:
    """
    Return a stable ``source_id`` string for an academic paper source.

    Strategy:
      - arxiv   → "arxiv:{normalised_id}"    (e.g. "arxiv:1706.03762")
      - pubmed  → "pubmed:{pmid}"            (e.g. "pubmed:12345678")
      - pdf / latex / markdown / unknown
               → "{stype}:{abs_path_or_url}"
    """
    s = url_or_path.strip()
    if stype == "arxiv":
        m = _ARXIV_ID_FROM_URL.search(s) or _BARE_ARXIV_RE.match(s)
        arxiv_id = m.group(1) if m else s
        return f"arxiv:{arxiv_id}"
    if stype == "pubmed":
        m = _PMID_RE.search(s)
        pmid = m.group(1) if m else (s if s.isdigit() else s)
        return f"pubmed:{pmid}"
    # For local files, normalise to absolute path for stability.
    try:
        resolved = str(Path(s).resolve())
    except Exception:
        resolved = s
    return f"{stype}:{resolved}"


def _source_id_for_ref(ref_doc: Document) -> str:
    """Return the ``source_id`` for a reference Document."""
    meta = ref_doc.metadata
    if meta.get("arxiv_id"):
        return f"arxiv:{meta['arxiv_id']}"
    if meta.get("pmid"):
        return f"pubmed:{meta['pmid']}"
    return f"ref:{meta.get('source_url', '')}"


def _inject_source_id(docs: list[Document], source_id: str) -> None:
    """Set ``source_id`` in the metadata of every Document in *docs* (in-place)."""
    for doc in docs:
        doc.metadata["source_id"] = source_id


# ── Per-source loaders ────────────────────────────────────────────────────────

def _load_paper(src: PaperSource, llm_cfg: dict | None) -> tuple[list[Document], dict]:
    url = src["url_or_path"]
    stype = src.get("source_type") or _detect_source_type(url)
    fetch_refs = src.get("fetch_references", False)
    depth = src.get("reference_depth", 1)
    top_n = src.get("reference_top_n", 10)
    _top_n = top_n if fetch_refs else 0
    _depth = depth if fetch_refs else 0

    if stype == "arxiv":
        from app.sources.arxiv import ArxivSource
        result = ArxivSource().fetch(url, top_n=_top_n, depth=_depth)
    elif stype == "pubmed":
        from app.sources.pubmed import PubmedSource
        result = PubmedSource().fetch(url, top_n=_top_n, depth=_depth)
    elif stype == "pdf":
        from app.sources.pdf import PDFSource
        result = PDFSource().fetch(url, top_n=_top_n, depth=_depth, llm_config=llm_cfg)
    elif stype == "latex":
        from app.sources.latex import LatexSource
        result = LatexSource().fetch(url, top_n=_top_n, depth=_depth, llm_config=llm_cfg)
    elif stype == "markdown":
        from app.sources.markdown import MarkdownSource
        result = MarkdownSource().fetch(url, top_n=_top_n, depth=_depth, llm_config=llm_cfg)
    else:
        raise ValueError(f"Unknown paper source type {stype!r} for {url!r}")

    primary_meta = result["primary"].metadata
    primary_id = _source_id_for_paper(stype, url)

    # Tag primary and every reference doc with stable source_ids.
    result["primary"].metadata["source_id"] = primary_id
    for ref in result["references"]:
        ref.metadata["source_id"] = _source_id_for_ref(ref)

    entry: dict = {
        "source_type":      stype,
        "source_id":        primary_id,
        "source_url":       url,
        "title":            primary_meta.get("title", ""),
        "authors":          primary_meta.get("authors", []),
        "year":             primary_meta.get("year"),
        "fetch_references": fetch_refs,
        "reference_depth":  depth,
        "reference_top_n":  top_n,
        "ingested_at":      None,
        "references": [
            {
                "id":            ref.metadata.get("arxiv_id") or ref.metadata.get("pmid", ""),
                "id_type":       "arxiv_id" if "arxiv_id" in ref.metadata else "pmid",
                "title":         ref.metadata.get("title", ""),
                "depth":         ref.metadata.get("depth", 1),
                "referenced_by": ref.metadata.get("referenced_by", []),
                "citation_count": ref.metadata.get("citation_count", 0),
                # source_id per reference document — already set on the doc above
                "source_id":     ref.metadata["source_id"],
            }
            for ref in result["references"]
        ],
    }
    return [result["primary"]] + result["references"], entry


def _load_youtube(
    src: YoutubeSourceConfig, username: str, cname: str
) -> tuple[list[Document], list[dict]]:
    from app.sources.youtube import YouTubeSource

    url = src["url"]
    lang = src.get("language", ["en"])
    docs = YouTubeSource().fetch(url, language=lang, username=username, collection_name=cname)

    # Build one metadata entry per unique video URL.
    entries: list[dict] = []
    seen: set[str] = set()
    for doc in docs:
        vid_url = doc.metadata.get("source_url", url)
        if vid_url in seen:
            continue
        seen.add(vid_url)
        playlist_url = doc.metadata.get("playlist_url")
        sid = f"youtube:{vid_url}"
        doc.metadata["source_id"] = sid
        entries.append(
            {
                "url":            vid_url,
                "source_id":      sid,
                "title":          doc.metadata.get("title", ""),
                "is_playlist":    playlist_url is not None,
                "playlist_url":   playlist_url,
                "author":         doc.metadata.get("author", ""),
                "length_seconds": doc.metadata.get("length_seconds", 0),
                "publish_date":   doc.metadata.get("publish_date", ""),
                "ingested_at":    None,
            }
        )
    # Ensure every doc (including non-first docs from same video) has source_id
    for doc in docs:
        if "source_id" not in doc.metadata:
            vid_url = doc.metadata.get("source_url", url)
            doc.metadata["source_id"] = f"youtube:{vid_url}"
    return docs, entries


def _load_github(src: GithubSourceConfig) -> tuple[list[Document], dict]:
    from app.sources.github import GitHubSource

    url = src["url"]
    branch = src.get("branch", "main")
    docs = GitHubSource().fetch(url)
    sid = f"github:{url}"
    _inject_source_id(docs, sid)
    return docs, {
        "url": url,
        "source_id": sid,
        "branch": branch,
        "file_count": len(docs),
        "ingested_at": None,
    }


def _load_webpage(
    src: WebSourceConfig, username: str, cname: str
) -> tuple[list[Document], dict]:
    url = src["url"]
    crawl = src.get("crawl", False)
    max_depth = src.get("max_depth", 2)

    if crawl:
        from app.sources.website import WebsiteSource
        docs = WebsiteSource().fetch(
            url, max_depth=max_depth, username=username, collection_name=cname
        )
    else:
        from app.sources.webpage import WebpageSource
        docs = WebpageSource().fetch(url, username=username, collection_name=cname)

    sid = f"webpage:{url}"
    _inject_source_id(docs, sid)
    return docs, {"url": url, "source_id": sid, "crawl": crawl, "page_count": len(docs), "ingested_at": None}


def _load_video(
    src: VideoSourceConfig, llm_cfg: dict | None, username: str, cname: str
) -> tuple[list[Document], dict]:
    from app.sources.video import VideoSource

    path = src["file_path"]
    docs = VideoSource().fetch(path, username=username, collection_name=cname, llm_config=llm_cfg)
    sid = f"video:{Path(path).resolve()}"
    _inject_source_id(docs, sid)
    return docs, {"file_path": path, "source_id": sid, "metadata": {"frame_count": len(docs)}, "ingested_at": None}


def _load_audio(
    src: AudioSourceConfig, username: str, cname: str
) -> tuple[list[Document], dict]:
    from app.sources.audio import AudioSource

    path = src["file_path"]
    model_size = src.get("model_size", "base")
    docs = AudioSource(model_size=model_size).fetch(
        path, username=username, collection_name=cname
    )
    first = docs[0] if docs else None
    sid = f"audio:{Path(path).resolve()}"
    _inject_source_id(docs, sid)
    return docs, {
        "file_path": path,
        "source_id": sid,
        "metadata": {
            "duration_seconds": first.metadata.get("duration_seconds", 0) if first else 0,
            "language":         first.metadata.get("language", "") if first else "",
            "word_count":       first.metadata.get("word_count", 0) if first else 0,
            "model_size":       model_size,
        },
        "ingested_at": None,
    }


def _load_image(
    src: ImageSourceConfig, llm_cfg: dict | None, username: str, cname: str
) -> tuple[list[Document], dict]:
    from app.sources.image import ImageSource

    path = src["file_path"]
    desc = src.get("description")
    docs = ImageSource().fetch(
        path, description=desc, llm_config=llm_cfg,
        username=username, collection_name=cname,
    )
    first = docs[0] if docs else None
    sid = f"image:{Path(path).resolve()}"
    _inject_source_id(docs, sid)
    return docs, {
        "file_path": path,
        "source_id": sid,
        "metadata": {
            "description": first.metadata.get("description", "") if first else "",
        },
        "ingested_at": None,
    }


def _load_dynamic_sources(
    sources: CollectionSources,
    username: str,
    creds_map: dict,
) -> tuple[list[dict], list[str]]:
    """
    Process every dynamic data source in *sources*, running sparse analysis
    where needed.  No Documents are produced — only storable metadata dicts.

    Returns
    -------
    (dynamic_entries, load_errors)
    """
    entries: list[dict] = []
    errors: list[str] = []

    for src in sources.get("dynamic_sources") or []:
        try:
            entry = load_dynamic_source(username, src, creds_map)
            entries.append(entry)
        except Exception as exc:
            msg = f"dynamic_source {src.get('source_type')!r} / {src.get('file_path') or src.get('credential_key')!r}: {exc}"
            errors.append(msg)
            print(f"[collection] ERROR loading {msg}", file=sys.stderr)

    return entries, errors


# ── Aggregate dispatcher ──────────────────────────────────────────────────────

# Maximum parallel workers for source loaders.
# LLM-backed sources (PDF, image, video) can spike provider rate limits;
# a default cap of 4 keeps concurrency reasonable without overwhelming APIs.
_DEFAULT_MAX_WORKERS = 4


def _load_all_sources(
    sources: CollectionSources,
    cfg: dict,
    username: str,
    collection_name: str,
    docs_dir: Path,
    start_index: int = 0,
    max_workers: int | None = _DEFAULT_MAX_WORKERS,
) -> tuple[dict, list[str], list[str]]:
    """
    Dispatch every source in *sources* to the appropriate adapter,
    loading all sources concurrently via a ``ThreadPoolExecutor``.

    Each source item is submitted as an independent future; results are
    processed as they complete (``as_completed``).  Pickling and the
    ``doc_counter`` increment happen only in the main thread after a
    future resolves, so there are no write races.

    Every source entry dict is enriched with:
      ``source_id``   — stable identifier (see module docstring)
      ``doc_paths``   — list of absolute paths to the pkl files for this source
      ``ingested_at`` — always ``None`` initially; set by the ingestion layer

    Returns
    -------
    (collection_fields, document_paths, load_errors)

    ``collection_fields``  — dict with keys papers/youtube/github_repos/webpages/
                             videos/audios/images/dynamic_data_sources.
    ``document_paths``     — flat list of all pkl paths written (all sources).
    ``load_errors``        — non-fatal per-source error strings.
    """
    llm_cfg = cfg.get("llm")
    creds_map: dict = cfg.get("data_source_creds") or {}

    papers_entries:  list[dict] = []
    youtube_entries: list[dict] = []
    github_entries:  list[dict] = []
    webpage_entries: list[dict] = []
    video_entries:   list[dict] = []
    audio_entries:   list[dict] = []
    image_entries:   list[dict] = []

    errors: list[str] = []
    doc_counter = start_index

    # Build a flat list of (callable, args, src_type, error_label) tasks.
    # Each task maps to ONE source item (not one category).
    tasks: list[tuple[Any, tuple, str, str]] = []

    for src in sources.get("papers") or []:
        tasks.append((_load_paper, (src, llm_cfg), "paper", str(src.get("url_or_path"))))
    for src in sources.get("youtube") or []:
        tasks.append((_load_youtube, (src, username, collection_name), "youtube", str(src.get("url"))))
    for src in sources.get("github") or []:
        tasks.append((_load_github, (src,), "github", str(src.get("url"))))
    for src in sources.get("webpages") or []:
        tasks.append((_load_webpage, (src, username, collection_name), "webpage", str(src.get("url"))))
    for src in sources.get("videos") or []:
        tasks.append((_load_video, (src, llm_cfg, username, collection_name), "video", str(src.get("file_path"))))
    for src in sources.get("audios") or []:
        tasks.append((_load_audio, (src, username, collection_name), "audio", str(src.get("file_path"))))
    for src in sources.get("images") or []:
        tasks.append((_load_image, (src, llm_cfg, username, collection_name), "image", str(src.get("file_path"))))

    # Submit all source-loading tasks concurrently.
    future_to_meta: dict[Any, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for fn, args, src_type, label in tasks:
            fut = executor.submit(fn, *args)
            future_to_meta[fut] = (src_type, label)

        # Process completions in the main thread to keep pickling race-free.
        for fut in as_completed(future_to_meta):
            src_type, label = future_to_meta[fut]
            try:
                result = fut.result()
            except Exception as exc:
                msg = f"{src_type} {label!r}: {exc}"
                errors.append(msg)
                print(f"[collection] ERROR loading {msg}", file=sys.stderr)
                continue

            # result is either (docs, entry) or (docs, list[entry])
            if src_type == "youtube":
                docs, entries = result  # list[dict]
            else:
                docs, entries = result  # single dict
                entries = [entries]

            # Inject primary source_id onto every doc that doesn't have one yet
            # (paper refs already have their own source_id set by the loader).
            for doc in docs:
                if "source_id" not in doc.metadata:
                    # Fallback: use the entry source_id if available.
                    fallback_sid = entries[0].get("source_id", "") if entries else ""
                    doc.metadata["source_id"] = fallback_sid

            # Pickle in the main thread; update counter.
            paths = _pickle_docs(docs, docs_dir, start_index=doc_counter)
            doc_counter += len(docs)

            # Distribute doc_paths per entry (for multi-entry types like youtube).
            # For youtube each entry = one video; docs are already tagged with
            # per-video source_id so we can split them by source_id.
            if src_type == "youtube" and len(entries) > 1:
                sid_to_paths: dict[str, list[str]] = {}
                for doc, path in zip(docs, paths):
                    s = doc.metadata.get("source_id", "")
                    sid_to_paths.setdefault(s, []).append(path)
                for entry in entries:
                    entry["doc_paths"] = sid_to_paths.get(entry["source_id"], [])
                youtube_entries.extend(entries)
            else:
                for entry in entries:
                    entry["doc_paths"] = paths
                if src_type == "paper":
                    papers_entries.extend(entries)
                elif src_type == "youtube":
                    youtube_entries.extend(entries)
                elif src_type == "github":
                    github_entries.extend(entries)
                elif src_type == "webpage":
                    webpage_entries.extend(entries)
                elif src_type == "video":
                    video_entries.extend(entries)
                elif src_type == "audio":
                    audio_entries.extend(entries)
                elif src_type == "image":
                    image_entries.extend(entries)

    # ── Dynamic data sources (no Documents; run synchronously) ────────────────
    dynamic_entries, dynamic_errors = _load_dynamic_sources(sources, username, creds_map)
    errors.extend(dynamic_errors)

    all_doc_paths: list[str] = [
        p
        for entries_list in (
            papers_entries, youtube_entries, github_entries,
            webpage_entries, video_entries, audio_entries, image_entries,
        )
        for entry in entries_list
        for p in entry.get("doc_paths", [])
    ]

    fields = {
        "papers":               papers_entries,
        "youtube":              youtube_entries,
        "github_repos":         github_entries,
        "webpages":             webpage_entries,
        "videos":               video_entries,
        "audios":               audio_entries,
        "images":               image_entries,
        "dynamic_data_sources": dynamic_entries,
    }
    return fields, all_doc_paths, errors


# ── Public API ────────────────────────────────────────────────────────────────

def create_collection(
    username: str,
    collection_name: str | None,
    sources: CollectionSources,
    config: dict | None = None,
    password: str | None = None,
) -> CollectionResult:
    """
    Load all sources described by *sources*, pickle each Document individually,
    and persist the collection metadata in the database.

    Parameters
    ----------
    username        : owning user's username
    collection_name : human-readable name.  A UUID hex string is used when not
                      supplied.  Conventionally ``"{username}_{label}"``.
    sources         : which sources to load
    config          : optional config overrides (provider, model, api_key, …)
    password        : user's password — enables merging the per-user DB config

    Returns
    -------
    CollectionResult
    """
    from app.users.config import resolve_config

    if not collection_name:
        collection_name = uuid.uuid4().hex

    effective_cfg = resolve_config(username, password, config)
    docs_dir = _docs_dir(username, collection_name)
    now = _now_iso()

    fields, doc_paths, errors = _load_all_sources(
        sources, effective_cfg, username, collection_name, docs_dir
    )

    collection_data: dict = {
        "collection_name": collection_name,
        "username":        username,
        "created_at":      now,
        "updated_at":      now,
        **fields,
    }

    save_collection(username, collection_name, collection_data)

    return CollectionResult(
        collection=collection_data,
        collection_name=collection_name,
        document_paths=doc_paths,
        load_errors=errors,
    )


def list_collections(username: str) -> list[dict]:
    """Return summary info for all collections owned by *username*."""
    return _db_list_collections(username)


def get_collection(username: str, collection_name: str) -> dict:
    """
    Return the full collection data dict.

    Raises
    ------
    KeyError  If the collection does not exist.
    """
    data = load_collection(username, collection_name)
    if data is None:
        raise KeyError(f"Collection {collection_name!r} not found for user {username!r}.")
    return data


def update_collection(
    username: str,
    collection_name: str,
    new_sources: CollectionSources,
    config: dict | None = None,
    password: str | None = None,
) -> CollectionResult:
    """
    Append new sources to an existing collection.

    Only the *new_sources* are fetched and pickled; existing Documents are not
    re-loaded.  The new metadata is merged into the stored collection dict and
    the DB record is updated.

    Raises
    ------
    KeyError  If the collection does not exist.
    """
    from app.users.config import resolve_config

    existing = load_collection(username, collection_name)
    if existing is None:
        raise KeyError(f"Collection {collection_name!r} not found for user {username!r}.")

    effective_cfg = resolve_config(username, password, config)
    docs_dir = _docs_dir(username, collection_name)
    start_index = _existing_doc_count(docs_dir)

    fields, doc_paths, errors = _load_all_sources(
        new_sources, effective_cfg, username, collection_name, docs_dir, start_index
    )

    # Merge new entries into the existing collection data.
    for key in (
        "papers", "youtube", "github_repos", "webpages",
        "videos", "audios", "images", "dynamic_data_sources",
    ):
        existing.setdefault(key, [])
        existing[key].extend(fields.get(key, []))
    existing["updated_at"] = _now_iso()

    update_collection_data(username, collection_name, existing)

    # Return paths to ALL documents in the collection (old + new).
    all_paths = sorted(str(p) for p in docs_dir.glob("doc_*.pkl"))

    return CollectionResult(
        collection=existing,
        collection_name=collection_name,
        document_paths=all_paths,
        load_errors=errors,
    )


def delete_collection(
    username: str,
    collection_name: str,
    config: dict | None = None,
    password: str | None = None,
) -> None:
    """
    Delete the collection record from the database, remove all associated
    data files (pkl files and any sidecar files written by the source adapters),
    and delete the corresponding vectors from the vector store.

    Parameters
    ----------
    username         : owning user's username
    collection_name  : collection to delete
    config           : optional config overrides — used for vector store access
    password         : user's password — enables per-user vector store credentials

    Raises
    ------
    KeyError  If the collection does not exist.
    """
    existing = load_collection(username, collection_name)
    if existing is None:
        raise KeyError(f"Collection {collection_name!r} not found for user {username!r}.")

    delete_collection_record(username, collection_name)

    data_dir = resolve_data_dir(username, collection_name)
    if data_dir.exists():
        shutil.rmtree(data_dir)

    # Clean up vectors from the vector store (non-fatal — store may not be configured).
    try:
        from app.storage.ingestion import delete_collection_vectors
        delete_collection_vectors(username, collection_name, config=config, password=password)
    except Exception as exc:
        print(
            f"[collection] WARNING: could not delete vectors for "
            f"{collection_name!r}: {exc}",
            file=sys.stderr,
        )


def reload_collection(
    username: str,
    collection_name: str,
    config: dict | None = None,
    password: str | None = None,
) -> CollectionResult:
    """
    Re-fetch all sources in an existing collection from scratch.

    The existing pkl files are deleted and recreated; sidecar files generated
    by the source adapters (audio transcripts, image descriptions, etc.) are
    preserved.  The ``updated_at`` timestamp is bumped in the DB.

    Raises
    ------
    KeyError  If the collection does not exist.
    """
    from app.users.config import resolve_config

    existing = load_collection(username, collection_name)
    if existing is None:
        raise KeyError(f"Collection {collection_name!r} not found for user {username!r}.")

    effective_cfg = resolve_config(username, password, config)

    # Wipe only the pk files — keep sidecar JSON files intact.
    docs_dir = _docs_dir(username, collection_name)
    if docs_dir.exists():
        for f in docs_dir.glob("doc_*.pkl"):
            f.unlink()

    # Reconstruct CollectionSources from the stored metadata.
    stored_sources: CollectionSources = {}

    if existing.get("papers"):
        stored_sources["papers"] = [
            PaperSource(
                url_or_path=p["source_url"],
                source_type=p["source_type"],
                fetch_references=p.get("fetch_references", False),
                reference_depth=p.get("reference_depth", 1),
                reference_top_n=p.get("reference_top_n", 10),
            )
            for p in existing["papers"]
        ]

    if existing.get("youtube"):
        # For playlist items, re-use the playlist URL to avoid duplicate fetches.
        yt_entries: list[YoutubeSourceConfig] = []
        seen_playlist_urls: set[str] = set()
        for y in existing["youtube"]:
            if y.get("is_playlist") and y.get("playlist_url"):
                pl = y["playlist_url"]
                if pl not in seen_playlist_urls:
                    yt_entries.append(YoutubeSourceConfig(url=pl))
                    seen_playlist_urls.add(pl)
            else:
                yt_entries.append(YoutubeSourceConfig(url=y["url"]))
        stored_sources["youtube"] = yt_entries

    if existing.get("github_repos"):
        stored_sources["github"] = [
            GithubSourceConfig(url=g["url"], branch=g.get("branch", "main"))
            for g in existing["github_repos"]
        ]

    if existing.get("webpages"):
        stored_sources["webpages"] = [
            WebSourceConfig(url=w["url"], crawl=w.get("crawl", False))
            for w in existing["webpages"]
        ]

    if existing.get("videos"):
        stored_sources["videos"] = [
            VideoSourceConfig(file_path=v["file_path"])
            for v in existing["videos"]
        ]

    if existing.get("audios"):
        stored_sources["audios"] = [
            AudioSourceConfig(file_path=a["file_path"])
            for a in existing["audios"]
        ]

    if existing.get("images"):
        stored_sources["images"] = [
            ImageSourceConfig(file_path=i["file_path"])
            for i in existing["images"]
        ]

    if existing.get("dynamic_data_sources"):
        # Preserve user-supplied descriptions; re-analyse auto-generated ones.
        dynamic_configs: list[DynamicDataSourceConfig] = []
        for d in existing["dynamic_data_sources"]:
            cfg_entry: DynamicDataSourceConfig = DynamicDataSourceConfig(
                source_type=d["source_type"]
            )
            # Carry through identifying fields.
            for field in ("credential_key", "file_path", "database", "table", "mongo_collection"):
                if d.get(field) is not None:
                    cfg_entry[field] = d[field]  # type: ignore[literal-required]
            # Only preserve user-supplied descriptions — let the rest be re-analysed.
            if d.get("description_source") == "user":
                cfg_entry["description"] = d["description"]
            dynamic_configs.append(cfg_entry)
        stored_sources["dynamic_sources"] = dynamic_configs

    fields, doc_paths, errors = _load_all_sources(
        stored_sources, effective_cfg, username, collection_name, docs_dir
    )

    now = _now_iso()
    new_data: dict = {
        "collection_name": collection_name,
        "username":        username,
        "created_at":      existing.get("created_at", now),
        "updated_at":      now,
        **fields,
    }
    update_collection_data(username, collection_name, new_data)

    return CollectionResult(
        collection=new_data,
        collection_name=collection_name,
        document_paths=doc_paths,
        load_errors=errors,
    )
