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
            "source_url":       "https://arxiv.org/abs/1706.03762",
            "title":            "Attention Is All You Need",
            "authors":          ["Vaswani", "..."],
            "year":             2017,
            "fetch_references": true,
            "reference_depth":  2,
            "reference_top_n":  10,
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
            "title":          "Rick Astley - Never Gonna Give You Up",
            "is_playlist":    false,
            "playlist_url":   null,
            "author":         "Rick Astley",
            "length_seconds": 213,
            "publish_date":   "2009-10-25"
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Required, TypedDict

from langchain_core.documents import Document

from app.sources.base import resolve_data_dir
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
    papers:   list[PaperSource]
    youtube:  list[YoutubeSourceConfig]
    github:   list[GithubSourceConfig]
    webpages: list[WebSourceConfig]
    videos:   list[VideoSourceConfig]
    audios:   list[AudioSourceConfig]
    images:   list[ImageSourceConfig]


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
    entry: dict = {
        "source_type":      stype,
        "source_url":       url,
        "title":            primary_meta.get("title", ""),
        "authors":          primary_meta.get("authors", []),
        "year":             primary_meta.get("year"),
        "fetch_references": fetch_refs,
        "reference_depth":  depth,
        "reference_top_n":  top_n,
        "references": [
            {
                "id":            ref.metadata.get("arxiv_id") or ref.metadata.get("pmid", ""),
                "id_type":       "arxiv_id" if "arxiv_id" in ref.metadata else "pmid",
                "title":         ref.metadata.get("title", ""),
                "depth":         ref.metadata.get("depth", 1),
                "referenced_by": ref.metadata.get("referenced_by", []),
                "citation_count": ref.metadata.get("citation_count", 0),
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
        entries.append(
            {
                "url":            vid_url,
                "title":          doc.metadata.get("title", ""),
                "is_playlist":    playlist_url is not None,
                "playlist_url":   playlist_url,
                "author":         doc.metadata.get("author", ""),
                "length_seconds": doc.metadata.get("length_seconds", 0),
                "publish_date":   doc.metadata.get("publish_date", ""),
            }
        )
    return docs, entries


def _load_github(src: GithubSourceConfig) -> tuple[list[Document], dict]:
    from app.sources.github import GitHubSource

    url = src["url"]
    branch = src.get("branch", "main")
    docs = GitHubSource().fetch(url)
    return docs, {"url": url, "branch": branch, "file_count": len(docs)}


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

    return docs, {"url": url, "crawl": crawl, "page_count": len(docs)}


def _load_video(
    src: VideoSourceConfig, llm_cfg: dict | None, username: str, cname: str
) -> tuple[list[Document], dict]:
    from app.sources.video import VideoSource

    path = src["file_path"]
    docs = VideoSource().fetch(path, username=username, collection_name=cname, llm_config=llm_cfg)
    return docs, {"file_path": path, "metadata": {"frame_count": len(docs)}}


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
    return docs, {
        "file_path": path,
        "metadata": {
            "duration_seconds": first.metadata.get("duration_seconds", 0) if first else 0,
            "language":         first.metadata.get("language", "") if first else "",
            "word_count":       first.metadata.get("word_count", 0) if first else 0,
            "model_size":       model_size,
        },
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
    return docs, {
        "file_path": path,
        "metadata": {
            "description": first.metadata.get("description", "") if first else "",
        },
    }


# ── Aggregate dispatcher ──────────────────────────────────────────────────────

def _load_all_sources(
    sources: CollectionSources,
    cfg: dict,
    username: str,
    collection_name: str,
    docs_dir: Path,
    start_index: int = 0,
) -> tuple[dict, list[str], list[str]]:
    """
    Dispatch every source in *sources* to the appropriate adapter.

    Returns
    -------
    (collection_fields, document_paths, load_errors)

    ``collection_fields``  — dict with keys papers/youtube/github_repos/webpages/
                             videos/audios/images, ready to merge into the
                             collection data dict.
    ``document_paths``     — absolute paths to all pkl files written.
    ``load_errors``        — non-fatal per-source error strings.
    """
    llm_cfg = cfg.get("llm")

    papers_entries:  list[dict] = []
    youtube_entries: list[dict] = []
    github_entries:  list[dict] = []
    webpage_entries: list[dict] = []
    video_entries:   list[dict] = []
    audio_entries:   list[dict] = []
    image_entries:   list[dict] = []

    all_doc_paths: list[str] = []
    errors:        list[str] = []
    doc_counter = start_index

    # ── Papers ────────────────────────────────────────────────────────────────
    for src in sources.get("papers") or []:
        try:
            docs, entry = _load_paper(src, llm_cfg)
            paths = _pickle_docs(docs, docs_dir, start_index=doc_counter)
            doc_counter += len(docs)
            all_doc_paths.extend(paths)
            papers_entries.append(entry)
        except Exception as exc:
            msg = f"paper {src.get('url_or_path')!r}: {exc}"
            errors.append(msg)
            print(f"[collection] ERROR loading {msg}", file=sys.stderr)

    # ── YouTube ───────────────────────────────────────────────────────────────
    for src in sources.get("youtube") or []:
        try:
            docs, entries = _load_youtube(src, username, collection_name)
            paths = _pickle_docs(docs, docs_dir, start_index=doc_counter)
            doc_counter += len(docs)
            all_doc_paths.extend(paths)
            youtube_entries.extend(entries)
        except Exception as exc:
            msg = f"youtube {src.get('url')!r}: {exc}"
            errors.append(msg)
            print(f"[collection] ERROR loading {msg}", file=sys.stderr)

    # ── GitHub ────────────────────────────────────────────────────────────────
    for src in sources.get("github") or []:
        try:
            docs, entry = _load_github(src)
            paths = _pickle_docs(docs, docs_dir, start_index=doc_counter)
            doc_counter += len(docs)
            all_doc_paths.extend(paths)
            github_entries.append(entry)
        except Exception as exc:
            msg = f"github {src.get('url')!r}: {exc}"
            errors.append(msg)
            print(f"[collection] ERROR loading {msg}", file=sys.stderr)

    # ── Web pages ─────────────────────────────────────────────────────────────
    for src in sources.get("webpages") or []:
        try:
            docs, entry = _load_webpage(src, username, collection_name)
            paths = _pickle_docs(docs, docs_dir, start_index=doc_counter)
            doc_counter += len(docs)
            all_doc_paths.extend(paths)
            webpage_entries.append(entry)
        except Exception as exc:
            msg = f"webpage {src.get('url')!r}: {exc}"
            errors.append(msg)
            print(f"[collection] ERROR loading {msg}", file=sys.stderr)

    # ── Videos ───────────────────────────────────────────────────────────────
    for src in sources.get("videos") or []:
        try:
            docs, entry = _load_video(src, llm_cfg, username, collection_name)
            paths = _pickle_docs(docs, docs_dir, start_index=doc_counter)
            doc_counter += len(docs)
            all_doc_paths.extend(paths)
            video_entries.append(entry)
        except Exception as exc:
            msg = f"video {src.get('file_path')!r}: {exc}"
            errors.append(msg)
            print(f"[collection] ERROR loading {msg}", file=sys.stderr)

    # ── Audio ─────────────────────────────────────────────────────────────────
    for src in sources.get("audios") or []:
        try:
            docs, entry = _load_audio(src, username, collection_name)
            paths = _pickle_docs(docs, docs_dir, start_index=doc_counter)
            doc_counter += len(docs)
            all_doc_paths.extend(paths)
            audio_entries.append(entry)
        except Exception as exc:
            msg = f"audio {src.get('file_path')!r}: {exc}"
            errors.append(msg)
            print(f"[collection] ERROR loading {msg}", file=sys.stderr)

    # ── Images ────────────────────────────────────────────────────────────────
    for src in sources.get("images") or []:
        try:
            docs, entry = _load_image(src, llm_cfg, username, collection_name)
            paths = _pickle_docs(docs, docs_dir, start_index=doc_counter)
            doc_counter += len(docs)
            all_doc_paths.extend(paths)
            image_entries.append(entry)
        except Exception as exc:
            msg = f"image {src.get('file_path')!r}: {exc}"
            errors.append(msg)
            print(f"[collection] ERROR loading {msg}", file=sys.stderr)

    fields = {
        "papers":       papers_entries,
        "youtube":      youtube_entries,
        "github_repos": github_entries,
        "webpages":     webpage_entries,
        "videos":       video_entries,
        "audios":       audio_entries,
        "images":       image_entries,
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
    for key in ("papers", "youtube", "github_repos", "webpages", "videos", "audios", "images"):
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


def delete_collection(username: str, collection_name: str) -> None:
    """
    Delete the collection record from the database and remove all associated
    data files (pkl files and any sidecar files written by the source adapters).

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
