"""
Vector store ingestion service for scibot collections.

This module is the bridge between the pickled Document files produced by
``app.sources.collection`` and the configured LangChain vector store.  It is
intentionally a separate step from data loading — call ``ingest_collection``
*after* ``create_collection``, or ``ingest_new_sources`` after
``update_collection``.

Public API
----------
ingest_documents(docs, username, collection_name, ...)   -> IngestResult
    Low-level: split, enrich, and store an arbitrary list of Documents.

ingest_collection(username, collection_name, ...)        -> IngestResult
    Ingest ALL source entries in a collection, auto-loading pkl files if
    present, or re-running the loader if any pkl file is missing.

ingest_new_sources(username, collection_name, ...)       -> IngestResult
    Ingest only the source entries that have not yet been ingested
    (``ingested_at is null``).  Safe to call repeatedly — no-op when
    everything is already ingested.

update_store(username, collection_name, source_ids, ...) -> IngestResult
    Re-ingest specific sources identified by their ``source_id``.  Deletes
    the existing vectors for those sources first, then re-ingests.

delete_collection_vectors(username, collection_name, ...) -> None
    Remove all vectors for a collection from the vector store.

Design notes
------------
* Vector collection naming:
    ``{username}__{collection_name}`` with non-[a-zA-Z0-9_] chars replaced
    by ``_``, truncated to 63 characters.  This gives full per-user isolation.

* Chunking:
    RecursiveCharacterTextSplitter for prose (default 800 tokens / 150 overlap).
    Language-aware splitter for GitHub source files (detected by extension).
    chunk_index and chunk_count are added to every chunk's metadata.

* Metadata enrichment:
    Every chunk preserves all original Document metadata (source_id, title,
    authors, arxiv_id, pmid, source_url, …) and gains:
      username, collection_name, vector_collection, ingested_at

* Duplicate-ingest guard:
    ``ingest_new_sources`` filters to ``ingested_at is null``.
    Full re-ingest via ``ingest_collection`` should be preceded by
    ``delete_collection_vectors`` to avoid duplicate vectors.

* Rate-limit protection:
    Source loading (when auto-triggered by the ingestion layer) respects
    the same ``max_workers=4`` concurrency cap used by collection.py.

* Filter-delete portability:
    Chroma supports metadata filter-delete natively.
    For all other providers, we fetch matching IDs first and delete by ID.
"""

from __future__ import annotations

from functools import lru_cache
import logging
import pickle
import re as _re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.documents import Document

from app.config.store import get_store
from app.users.collections_db import load_collection, update_collection_data
from app.users.config import resolve_config

logger = logging.getLogger(__name__)


# ── TypedDicts ────────────────────────────────────────────────────────────────

class IngestResult(TypedDict):
    """Return value of all public ingestion functions."""
    collection_name:  str
    username:         str
    ingested_sources: int        # number of source entries ingested this call
    total_chunks:     int        # total vector chunks written
    errors:           list[str]  # non-fatal per-source errors


class StoreSettingsDriftError(ValueError):
    """
    Raised when an ingest call detects that the current effective configuration
    differs from the settings that were active when the collection was last
    ingested.

    Changing the distance function or embedding model after data has been
    ingested produces vectors in an incompatible space — similarity searches
    would return meaningless results.

    Resolution
    ----------
    1. Call ``delete_collection_vectors(username, collection_name)`` to wipe
       the existing vectors from the store.
    2. Re-run ``ingest_collection(username, collection_name)`` with the updated
       settings to rebuild the vector index from scratch.

    Attributes
    ----------
    username          : owning user
    collection_name   : logical collection name
    changed_settings  : list of dicts, each with keys "key", "was", "now"
    """

    def __init__(
        self,
        username: str,
        collection_name: str,
        changed_settings: list[dict],
    ) -> None:
        self.username = username
        self.collection_name = collection_name
        self.changed_settings = changed_settings

        lines = [
            f"Store settings have changed since collection {collection_name!r} "
            f"(user: {username!r}) was last ingested.",
            "Re-ingesting with a different distance function or embedding model "
            "would mix incompatible vectors in the same index.",
            "",
            "Changed settings:",
        ]
        for s in changed_settings:
            lines.append(f"  {s['key']}: was {s['was']!r}, now {s['now']!r}")
        lines += [
            "",
            "To apply the new settings:",
            "  1. delete_collection_vectors(username, collection_name)  # wipe old vectors",
            "  2. ingest_collection(username, collection_name)           # rebuild fresh",
        ]
        super().__init__("\n".join(lines))


# ── Code-extension detection (for Language-aware splitting) ──────────────────

_CODE_EXTENSIONS: frozenset[str] = frozenset({
    # Python
    "py", "pyi",
    # TypeScript / JavaScript
    "ts", "tsx", "js", "jsx", "mjs", "cjs",
    # Java / Kotlin / Scala
    "java", "kt", "kts", "scala",
    # C / C++ / C#
    "c", "h", "cpp", "cxx", "cc", "hpp", "hxx", "cs",
    # Go / Rust / Swift
    "go", "rs", "swift",
    # Ruby / PHP / Perl
    "rb", "php", "pl", "pm",
    # Shells
    "sh", "bash", "zsh", "fish",
    # HTML / CSS
    "html", "htm", "css", "scss", "sass",
    # SQL
    "sql",
    # Config / data — NOT split as code but listed for exclusion awareness
    # (json, yaml, toml, ini are treated as prose)
})

# Map file extension → LangChain Language enum value
_EXT_TO_LANGUAGE: dict[str, str] = {
    "py": "python", "pyi": "python",
    "ts": "ts", "tsx": "ts", "js": "js", "jsx": "js", "mjs": "js", "cjs": "js",
    "java": "java", "kt": "java", "kts": "java", "scala": "scala",
    "c": "c", "h": "c", "cpp": "cpp", "cxx": "cpp", "cc": "cpp",
    "hpp": "cpp", "hxx": "cpp", "cs": "csharp",
    "go": "go", "rs": "rust", "swift": "swift",
    "rb": "ruby", "php": "php",
    "sh": "bash", "bash": "bash", "zsh": "bash",
    "html": "html", "htm": "html",
    "sol": "sol",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_UNSAFE_CHARS = _re.compile(r"[^a-zA-Z0-9_]")


def _vector_collection_name(username: str, collection_name: str) -> str:
    """
    Return a sanitised vector store collection name.

    Format: ``{username}__{collection_name}``
    All characters outside ``[a-zA-Z0-9_]`` are replaced with ``_``.
    Result is truncated to 63 characters to stay within most store limits.
    """
    raw = f"{username}__{collection_name}"
    sanitised = _UNSAFE_CHARS.sub("_", raw)
    return sanitised[:63]


def _store_for_collection(
    username: str,
    collection_name: str,
    effective_cfg: dict,
) -> Any:
    """
    Build a LangChain vector store instance scoped to this collection.

    The vector store ``collection_name`` (and ``namespace`` for Pinecone) is
    set to ``_vector_collection_name(username, collection_name)`` so that
    every user's data is fully isolated.
    """
    vcname = _vector_collection_name(username, collection_name)
    store_cfg = dict(effective_cfg.get("store") or {})
    store_cfg["collection_name"] = vcname
    # Pinecone uses namespace for sub-index isolation
    if store_cfg.get("provider") == "pinecone":
        store_cfg.setdefault("namespace", vcname)

    embedding_cfg = effective_cfg.get("embedding")
    if embedding_cfg:
        store_cfg.setdefault("embedding", embedding_cfg)
    return get_store(store_cfg)


def _split_docs(
    docs: list[Document],
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> list[Document]:
    """
    Split Documents into chunks.

    - Prose documents use ``RecursiveCharacterTextSplitter``.
    - GitHub source-code documents (detected by ``source`` file extension in
      metadata) use a ``Language``-aware splitter when the extension is
      recognised; falls back to the prose splitter otherwise.

    Every chunk gains two metadata keys:
      ``chunk_index``  — 0-based position within the parent document's chunks
      ``chunk_count``  — total number of chunks produced from that parent
    """
    all_chunks: list[Document] = []

    for doc in docs:
        # Detect whether this is a GitHub code file
        source_path: str = doc.metadata.get("source", "") or doc.metadata.get("file_path", "")
        ext = Path(source_path).suffix.lstrip(".").lower() if source_path else ""
        lang_key = _EXT_TO_LANGUAGE.get(ext) if ext in _CODE_EXTENSIONS else None

        splitter = _get_splitter(lang_key, chunk_size, chunk_overlap)

        raw_chunks = splitter.split_documents([doc])
        for idx, chunk in enumerate(raw_chunks):
            chunk.metadata["chunk_index"] = idx
            chunk.metadata["chunk_count"] = len(raw_chunks)
        all_chunks.extend(raw_chunks)

    return all_chunks


@lru_cache(maxsize=32)
def _get_prose_splitter(chunk_size: int, chunk_overlap: int) -> Any:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )


@lru_cache(maxsize=128)
def _get_code_splitter(
    lang_key: str,
    chunk_size: int,
    chunk_overlap: int,
) -> Any | None:
    from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

    try:
        lang_enum = Language(lang_key)
        return RecursiveCharacterTextSplitter.from_language(
            language=lang_enum,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    except (ValueError, AttributeError):
        return None


def _get_splitter(
    lang_key: str | None,
    chunk_size: int,
    chunk_overlap: int,
) -> Any:
    prose_splitter = _get_prose_splitter(chunk_size, chunk_overlap)
    if not lang_key:
        return prose_splitter

    return _get_code_splitter(lang_key, chunk_size, chunk_overlap) or prose_splitter


def _enrich_chunks(
    chunks: list[Document],
    username: str,
    collection_name: str,
    ingested_at: str,
) -> list[Document]:
    """
    Add ingestion-level metadata to every chunk without losing any original
    metadata (source_id, title, authors, arxiv_id, pmid, source_url, etc.).

    Added keys:
      ``username``           — owning user
      ``collection_name``    — logical collection name
      ``vector_collection``  — actual vector store collection name
      ``ingested_at``        — ISO-8601 UTC ingest timestamp
    """
    vcname = _vector_collection_name(username, collection_name)
    for chunk in chunks:
        chunk.metadata["username"] = username
        chunk.metadata["collection_name"] = collection_name
        chunk.metadata["vector_collection"] = vcname
        chunk.metadata["ingested_at"] = ingested_at
    return chunks


def _load_source_docs(
    entry: dict,
    src_type: str,
    username: str,
    collection_name: str,
    effective_cfg: dict,
) -> list[Document]:
    """
    Return the Documents for a single source entry.

    Strategy:
    1. If ``entry["doc_paths"]`` is present and **all** files exist on disk,
       unpickle and return them directly (fast path — no re-fetch needed).
    2. If any file is missing, re-run the appropriate source loader to
       regenerate the pkl files, then update ``entry["doc_paths"]`` in place.
    3. Raise ``ValueError`` if neither path is viable.

    The caller is responsible for persisting the updated collection data to
    the DB when ``entry["doc_paths"]`` is modified (the ingestion functions
    all do this).
    """
    doc_paths: list[str] = entry.get("doc_paths") or []
    if doc_paths and all(Path(p).exists() for p in doc_paths):
        docs: list[Document] = []
        for p in doc_paths:
            with open(p, "rb") as fh:
                docs.append(pickle.load(fh))  # noqa: S301 — trusted internal pickle
        return docs

    # One or more pkl files are missing — re-run the loader.
    from app.sources.collection import (
        _docs_dir,
        _existing_doc_count,
        _load_audio,
        _load_github,
        _load_image,
        _load_paper,
        _load_video,
        _load_webpage,
        _load_youtube,
        _pickle_docs,
        PaperSource,
        YoutubeSourceConfig,
        GithubSourceConfig,
        WebSourceConfig,
        VideoSourceConfig,
        AudioSourceConfig,
        ImageSourceConfig,
    )

    llm_cfg = effective_cfg.get("llm")
    docs_dir = _docs_dir(username, collection_name)
    start_index = _existing_doc_count(docs_dir)

    if src_type == "paper":
        src = PaperSource(
            url_or_path=entry["source_url"],
            source_type=entry["source_type"],
            fetch_references=entry.get("fetch_references", False),
            reference_depth=entry.get("reference_depth", 1),
            reference_top_n=entry.get("reference_top_n", 10),
        )
        docs, _ = _load_paper(src, llm_cfg)
    elif src_type == "youtube":
        src = YoutubeSourceConfig(url=entry["url"])
        docs_raw, _ = _load_youtube(src, username, collection_name)
        # Filter docs belonging to this specific video entry
        docs = [d for d in docs_raw if d.metadata.get("source_url", "") == entry["url"]]
        if not docs:
            docs = docs_raw
    elif src_type == "github":
        src = GithubSourceConfig(url=entry["url"], branch=entry.get("branch", "main"))
        docs, _ = _load_github(src)
    elif src_type == "webpage":
        src = WebSourceConfig(url=entry["url"], crawl=entry.get("crawl", False))
        docs, _ = _load_webpage(src, username, collection_name)
    elif src_type == "video":
        src = VideoSourceConfig(file_path=entry["file_path"])
        docs, _ = _load_video(src, llm_cfg, username, collection_name)
    elif src_type == "audio":
        src = AudioSourceConfig(
            file_path=entry["file_path"],
            model_size=entry.get("metadata", {}).get("model_size", "base"),
        )
        docs, _ = _load_audio(src, username, collection_name)
    elif src_type == "image":
        src = ImageSourceConfig(file_path=entry["file_path"])
        docs, _ = _load_image(src, llm_cfg, username, collection_name)
    else:
        raise ValueError(
            f"Cannot reload source type {src_type!r} — "
            "pkl files are missing and no loader exists for this type."
        )

    new_paths = _pickle_docs(docs, docs_dir, start_index=start_index)
    entry["doc_paths"] = new_paths
    return docs


def _entry_source_label(entry: dict) -> str:
    return entry.get("source_id", repr(entry.get("url") or entry.get("file_path")))


def _flush_chunk_batch(
    store: Any,
    batch: list[tuple[str, dict, list[Document]]],
    ingested_at: str,
) -> tuple[int, int, list[str]]:
    if not batch:
        return 0, 0, []

    all_chunks = [chunk for _, _, chunks in batch for chunk in chunks]
    if not all_chunks:
        return 0, 0, []

    try:
        store.add_documents(all_chunks)
        for _, entry, _ in batch:
            entry["ingested_at"] = ingested_at
        return len(batch), len(all_chunks), []
    except Exception as exc:
        logger.warning(
            "Batched store.add_documents failed; falling back to per-source writes: %s", exc
        )

    errors: list[str] = []
    ingested_source_count = 0
    total_chunks = 0
    for src_type, entry, chunks in batch:
        try:
            store.add_documents(chunks)
            entry["ingested_at"] = ingested_at
            ingested_source_count += 1
            total_chunks += len(chunks)
        except Exception as source_exc:
            msg = f"{src_type} {_entry_source_label(entry)!r}: {source_exc}"
            errors.append(msg)
            logger.error("Ingestion error — %s", msg, exc_info=True)

    return ingested_source_count, total_chunks, errors


def _ingest_entries(
    entries: list[tuple[str, dict]],
    store: Any,
    username: str,
    collection_name: str,
    effective_cfg: dict,
    ingested_at: str,
) -> tuple[int, int, list[str]]:
    chunk_size = int((effective_cfg.get("chunk_size") or 800))
    chunk_overlap = int((effective_cfg.get("chunk_overlap") or 150))
    batch_size = max(1, int(effective_cfg.get("ingest_batch_size") or 256))

    all_errors: list[str] = []
    total_chunks = 0
    ingested_source_count = 0
    pending_batch: list[tuple[str, dict, list[Document]]] = []
    pending_chunk_count = 0

    for src_type, entry in entries:
        try:
            docs = _load_source_docs(entry, src_type, username, collection_name, effective_cfg)
            if not docs:
                continue

            chunks = _split_docs(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            _enrich_chunks(chunks, username, collection_name, ingested_at)

            pending_batch.append((src_type, entry, chunks))
            pending_chunk_count += len(chunks)
            if pending_chunk_count < batch_size:
                continue

            batch_sources, batch_chunks, batch_errors = _flush_chunk_batch(
                store,
                pending_batch,
                ingested_at,
            )
            ingested_source_count += batch_sources
            total_chunks += batch_chunks
            all_errors.extend(batch_errors)
            pending_batch = []
            pending_chunk_count = 0
        except Exception as exc:
            msg = f"{src_type} {_entry_source_label(entry)!r}: {exc}"
            all_errors.append(msg)
            logger.error("Ingestion error — %s", msg, exc_info=True)

    if pending_batch:
        batch_sources, batch_chunks, batch_errors = _flush_chunk_batch(
            store,
            pending_batch,
            ingested_at,
        )
        ingested_source_count += batch_sources
        total_chunks += batch_chunks
        all_errors.extend(batch_errors)

    return ingested_source_count, total_chunks, all_errors


def _all_source_entries(collection_data: dict) -> list[tuple[str, dict]]:
    """
    Yield ``(src_type, entry)`` for every source entry in a collection dict.

    ``src_type`` is one of: "paper", "youtube", "github", "webpage",
    "video", "audio", "image".  Dynamic data sources (no Documents) are
    excluded.
    """
    entries: list[tuple[str, dict]] = []
    for entry in collection_data.get("papers") or []:
        entries.append(("paper", entry))
    for entry in collection_data.get("youtube") or []:
        entries.append(("youtube", entry))
    for entry in collection_data.get("github_repos") or []:
        entries.append(("github", entry))
    for entry in collection_data.get("webpages") or []:
        entries.append(("webpage", entry))
    for entry in collection_data.get("videos") or []:
        entries.append(("video", entry))
    for entry in collection_data.get("audios") or []:
        entries.append(("audio", entry))
    for entry in collection_data.get("images") or []:
        entries.append(("image", entry))
    return entries


def _delete_by_source_ids(store: Any, source_ids: list[str], provider: str) -> None:
    """
    Delete all vector chunks whose ``source_id`` metadata matches any of
    the given *source_ids*.

    Provider-specific strategies:
    - **Chroma**: native metadata filter-delete
      (``store.delete(where={"source_id": {"$in": source_ids}})``)
    - **Pinecone**: filter-delete via ``store.delete(filter=...)``
    - **Qdrant**: filter-delete via qdrant ``Filter`` models
    - **Milvus / MongoDB / Postgres**: fetch matching IDs first,
      then ``store.delete(ids=...)``
    """
    if not source_ids:
        return

    try:
        if provider == "chroma":
            store.delete(where={"source_id": {"$in": source_ids}})

        elif provider == "pinecone":
            store.delete(filter={"source_id": {"$in": source_ids}})

        elif provider == "qdrant":
            from qdrant_client.models import FieldCondition, Filter, MatchAny
            store.delete(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="metadata.source_id",
                            match=MatchAny(any=source_ids),
                        )
                    ]
                )
            )

        else:
            # Fallback: fetch IDs by metadata filter, then delete by ID.
            # Works for Milvus, MongoDB, Postgres, and any future providers.
            matched_docs = store.get(where={"source_id": {"$in": source_ids}})
            if matched_docs:
                ids_to_delete = [
                    doc.metadata.get("id") or doc.id
                    for doc in matched_docs
                    if hasattr(doc, "metadata") or hasattr(doc, "id")
                ]
                if ids_to_delete:
                    store.delete(ids=ids_to_delete)

    except Exception as exc:
        # Non-fatal: log and continue (vectors may already be absent).
        print(f"[ingestion] WARNING: filter-delete failed ({exc})", file=sys.stderr)

# ── Store-settings snapshot + drift detection ────────────────────────────────

# (section_name, cfg_path_tuple, cfg_leaf_key)
_SNAPSHOT_KEYS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("provider",             ("store",),     "provider"),
    ("distance_function",   ("store",),     "distance_function"),
    ("distance_strategy",   ("store",),     "distance_strategy"),
    ("embedding_provider",  ("embedding",), "provider"),
    ("embedding_model",     ("embedding",), "model"),
    ("embedding_dimensions", ("embedding",), "dimensions"),
)


def _snapshot_store_settings(effective_cfg: dict) -> dict:
    """
    Extract the subset of *effective_cfg* that is relevant for re-ingest
    compatibility into a flat, JSON-serialisable dict.

    The snapshot is stored in the collection data under ``store_settings``
    after each successful ingest.  On subsequent ingest calls it is compared
    against the current effective config to detect incompatible changes.

    Snapshot keys
    -------------
    provider             – store.provider (e.g. "chroma")
    distance_function    – store.distance_function (Chroma HNSW metric)
    distance_strategy    – store.distance_strategy (Postgres pgvector)
    embedding_provider   – embedding.provider
    embedding_model      – embedding.model
    embedding_dimensions – embedding.dimensions (OpenAI / Google GenAI)
    """
    snapshot: dict = {}
    for snap_key, cfg_path, cfg_leaf in _SNAPSHOT_KEYS:
        sub: Any = effective_cfg
        for seg in cfg_path:
            sub = sub.get(seg) if isinstance(sub, dict) else None
        snapshot[snap_key] = sub.get(cfg_leaf) if isinstance(sub, dict) else None
    return snapshot


def _check_and_assert_no_drift(
    collection_data: dict,
    effective_cfg: dict,
    username: str,
    collection_name: str,
) -> None:
    """
    Raise ``StoreSettingsDriftError`` if the current effective configuration
    differs from the snapshot stored in *collection_data* at the last ingest.

    A missing ``store_settings`` key (collection not yet ingested) is treated
    as no-drift — the first ingest always proceeds without error.
    """
    stored = collection_data.get("store_settings")
    if not stored:
        return  # never been ingested — nothing to drift from

    current = _snapshot_store_settings(effective_cfg)
    changed = [
        {"key": k, "was": stored.get(k), "now": current.get(k)}
        for k in current
        if current.get(k) != stored.get(k)
    ]
    if changed:
        raise StoreSettingsDriftError(username, collection_name, changed)

# ── Public API ────────────────────────────────────────────────────────────────

def ingest_documents(
    docs: list[Document],
    username: str,
    collection_name: str,
    config: dict | None = None,
    password: str | None = None,
    store: Any | None = None,
) -> IngestResult:
    """
    Low-level ingestion: split, enrich, and write *docs* to the vector store.

    All documents in *docs* must already have ``source_id`` set in their
    metadata (this is done automatically by ``app.sources.collection``).

    Parameters
    ----------
    docs             : list of Documents to ingest
    username         : owning user
    collection_name  : logical collection name (used for metadata enrichment
                       and to derive the vector store collection name)
    config           : optional config overrides (store, embedding, …)
    password         : user password for per-user config decryption
    store            : pre-built LangChain vector store instance.  When
                       provided, ``config`` and ``password`` are used only
                       for chunking settings; no new store is constructed.

    Config keys
    -----------
    chunk_size    : int, default 800
    chunk_overlap : int, default 150

    Returns
    -------
    IngestResult
    """
    effective_cfg = resolve_config(username, password, config)
    chunk_size = int((effective_cfg.get("chunk_size") or 800))
    chunk_overlap = int((effective_cfg.get("chunk_overlap") or 150))

    if store is None:
        store = _store_for_collection(username, collection_name, effective_cfg)

    ingested_at = _now_iso()
    chunks = _split_docs(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    _enrich_chunks(chunks, username, collection_name, ingested_at)

    errors: list[str] = []
    if chunks:
        try:
            store.add_documents(chunks)
        except Exception as exc:
            errors.append(f"store.add_documents failed: {exc}")
            print(f"[ingestion] ERROR: {errors[-1]}", file=sys.stderr)

    return IngestResult(
        collection_name=collection_name,
        username=username,
        ingested_sources=len({d.metadata.get("source_id", "") for d in docs}),
        total_chunks=len(chunks),
        errors=errors,
    )


def ingest_collection(
    username: str,
    collection_name: str,
    config: dict | None = None,
    password: str | None = None,
) -> IngestResult:
    """
    Ingest ALL source entries in an existing collection into the vector store.

    Documents are loaded from their pkl files on disk.  If any pkl file is
    missing for a source, the appropriate loader is automatically re-run to
    regenerate them before ingestion.

    After a successful ingest the following fields are stamped in the DB:
      - ``ingested_at`` on every source entry
      - ``vector_collection`` at the top level of the collection dict

    Parameters
    ----------
    username         : owning user
    collection_name  : collection to ingest; raises ``KeyError`` if not found
    config           : optional config overrides
    password         : user password for per-user config decryption

    Returns
    -------
    IngestResult
    """
    collection_data = load_collection(username, collection_name)
    if collection_data is None:
        raise KeyError(f"Collection {collection_name!r} not found for user {username!r}.")

    effective_cfg = resolve_config(username, password, config)
    _check_and_assert_no_drift(collection_data, effective_cfg, username, collection_name)
    store = _store_for_collection(username, collection_name, effective_cfg)
    vcname = _vector_collection_name(username, collection_name)
    ingested_at = _now_iso()

    ingested_source_count, total_chunks, all_errors = _ingest_entries(
        _all_source_entries(collection_data),
        store,
        username,
        collection_name,
        effective_cfg,
        ingested_at,
    )

    collection_data["vector_collection"] = vcname
    collection_data["store_settings"] = _snapshot_store_settings(effective_cfg)
    collection_data["updated_at"] = ingested_at
    update_collection_data(username, collection_name, collection_data)

    return IngestResult(
        collection_name=collection_name,
        username=username,
        ingested_sources=ingested_source_count,
        total_chunks=total_chunks,
        errors=all_errors,
    )


def ingest_new_sources(
    username: str,
    collection_name: str,
    config: dict | None = None,
    password: str | None = None,
) -> IngestResult:
    """
    Ingest only the source entries that have not yet been ingested
    (``ingested_at is null``).

    This is the recommended function to call after ``update_collection``
    adds new sources to an existing collection — only the newly added
    sources are fetched and ingested; existing vectors are untouched.

    Returns an empty ``IngestResult`` (zero chunks) if every source entry
    already has ``ingested_at`` set.

    Parameters
    ----------
    username         : owning user
    collection_name  : collection to update; raises ``KeyError`` if not found
    config           : optional config overrides
    password         : user password for per-user config decryption

    Returns
    -------
    IngestResult
    """
    collection_data = load_collection(username, collection_name)
    if collection_data is None:
        raise KeyError(f"Collection {collection_name!r} not found for user {username!r}.")

    # Filter to un-ingested entries only.
    pending = [
        (src_type, entry)
        for src_type, entry in _all_source_entries(collection_data)
        if not entry.get("ingested_at")
    ]

    if not pending:
        return IngestResult(
            collection_name=collection_name,
            username=username,
            ingested_sources=0,
            total_chunks=0,
            errors=[],
        )

    effective_cfg = resolve_config(username, password, config)
    _check_and_assert_no_drift(collection_data, effective_cfg, username, collection_name)
    store = _store_for_collection(username, collection_name, effective_cfg)
    vcname = _vector_collection_name(username, collection_name)
    ingested_at = _now_iso()

    ingested_source_count, total_chunks, all_errors = _ingest_entries(
        pending,
        store,
        username,
        collection_name,
        effective_cfg,
        ingested_at,
    )

    # Ensure vector_collection is stamped at the top level.
    collection_data["vector_collection"] = vcname
    collection_data["store_settings"] = _snapshot_store_settings(effective_cfg)
    collection_data["updated_at"] = ingested_at
    update_collection_data(username, collection_name, collection_data)

    return IngestResult(
        collection_name=collection_name,
        username=username,
        ingested_sources=ingested_source_count,
        total_chunks=total_chunks,
        errors=all_errors,
    )


def update_store(
    username: str,
    collection_name: str,
    source_ids: list[str],
    config: dict | None = None,
    password: str | None = None,
) -> IngestResult:
    """
    Re-ingest specific sources identified by their ``source_id``.

    Workflow:
    1. Locate source entries matching any of the given *source_ids*.
    2. Delete existing vectors for those source IDs from the vector store.
    3. Reload Documents (from pkl or by re-running the loader).
    4. Re-ingest the fresh chunks.
    5. Stamp ``ingested_at`` on the updated entries in the DB.

    This is the function to call when a source's content has changed (e.g.
    a webpage has been updated, or an audio transcription was improved) and
    only those vectors need to be refreshed — without touching the rest of
    the collection.

    Parameters
    ----------
    username         : owning user
    collection_name  : collection to update; raises ``KeyError`` if not found
    source_ids       : list of ``source_id`` strings to re-ingest
    config           : optional config overrides
    password         : user password for per-user config decryption

    Raises
    ------
    KeyError    If the collection does not exist.
    ValueError  If no source entry matches any of the given *source_ids*.

    Returns
    -------
    IngestResult
    """
    collection_data = load_collection(username, collection_name)
    if collection_data is None:
        raise KeyError(f"Collection {collection_name!r} not found for user {username!r}.")

    target_set = set(source_ids)
    matched: list[tuple[str, dict]] = [
        (src_type, entry)
        for src_type, entry in _all_source_entries(collection_data)
        if entry.get("source_id") in target_set
    ]

    if not matched:
        raise ValueError(
            f"No source entries found for source_ids {source_ids!r} "
            f"in collection {collection_name!r}."
        )

    effective_cfg = resolve_config(username, password, config)
    _check_and_assert_no_drift(collection_data, effective_cfg, username, collection_name)
    provider = (effective_cfg.get("store") or {}).get("provider", "chroma")
    store = _store_for_collection(username, collection_name, effective_cfg)
    vcname = _vector_collection_name(username, collection_name)
    ingested_at = _now_iso()

    # Step 1: delete existing vectors for targeted source_ids.
    _delete_by_source_ids(store, source_ids, provider)

    ingested_source_count, total_chunks, all_errors = _ingest_entries(
        matched,
        store,
        username,
        collection_name,
        effective_cfg,
        ingested_at,
    )

    collection_data["vector_collection"] = vcname
    collection_data["store_settings"] = _snapshot_store_settings(effective_cfg)
    collection_data["updated_at"] = ingested_at
    update_collection_data(username, collection_name, collection_data)

    return IngestResult(
        collection_name=collection_name,
        username=username,
        ingested_sources=ingested_source_count,
        total_chunks=total_chunks,
        errors=all_errors,
    )


def check_reingest_required(
    username: str,
    collection_name: str,
    config: dict | None = None,
    password: str | None = None,
) -> dict:
    """
    Non-raising check for whether the current effective config is compatible
    with the last ingest of this collection.

    Call this *before* saving new user config to surface a warning in the UI
    or API response without triggering a hard failure mid-ingest.

    Parameters
    ----------
    username         : owning user
    collection_name  : collection to inspect; raises ``KeyError`` if not found
    config           : optional config overrides — same dict as the next ingest
    password         : user password for per-user config decryption

    Returns
    -------
    dict with two keys:
      ``reingest_required`` – ``True`` if any setting has drifted from the
                              last ingest, ``False`` otherwise (or when the
                              collection has never been ingested).
      ``changed_settings``  – list of dicts, each with ``key``, ``was``,
                              ``now``.  Empty when ``reingest_required`` is
                              ``False``.
    """
    collection_data = load_collection(username, collection_name)
    if collection_data is None:
        raise KeyError(f"Collection {collection_name!r} not found for user {username!r}.")

    stored = collection_data.get("store_settings")
    if not stored:
        return {"reingest_required": False, "changed_settings": []}

    effective_cfg = resolve_config(username, password, config)
    current = _snapshot_store_settings(effective_cfg)
    changed = [
        {"key": k, "was": stored.get(k), "now": current.get(k)}
        for k in current
        if current.get(k) != stored.get(k)
    ]
    return {"reingest_required": bool(changed), "changed_settings": changed}


def delete_collection_vectors(
    username: str,
    collection_name: str,
    config: dict | None = None,
    password: str | None = None,
) -> None:
    """
    Remove all vectors associated with a collection from the vector store.

    For Chroma, the entire vector collection is dropped atomically.
    For all other providers, vectors are deleted by ``source_id`` filter
    using ``_delete_by_source_ids``.

    This function is called automatically by ``delete_collection`` in
    ``app.sources.collection`` (non-fatal — errors are logged as warnings).
    It can also be called manually before a full re-ingest to avoid
    duplicate vectors.

    Parameters
    ----------
    username         : owning user
    collection_name  : collection whose vectors should be deleted
    config           : optional config overrides
    password         : user password for per-user config decryption
    """
    collection_data = load_collection(username, collection_name)
    effective_cfg = resolve_config(username, password, config)
    provider = (effective_cfg.get("store") or {}).get("provider", "chroma")
    vcname = _vector_collection_name(username, collection_name)

    try:
        store = _store_for_collection(username, collection_name, effective_cfg)
    except Exception as exc:
        print(
            f"[ingestion] WARNING: cannot connect to vector store to delete "
            f"vectors for {collection_name!r}: {exc}",
            file=sys.stderr,
        )
        return

    try:
        if provider == "chroma":
            # Drop the entire Chroma collection — fastest and most complete.
            store._client.delete_collection(vcname)
            return

        # For all other providers: delete by source_id filter.
        if collection_data is not None:
            all_source_ids = [
                entry.get("source_id", "")
                for _, entry in _all_source_entries(collection_data)
                if entry.get("source_id")
            ]
            _delete_by_source_ids(store, all_source_ids, provider)

    except Exception as exc:
        print(
            f"[ingestion] WARNING: error while deleting vectors for "
            f"{collection_name!r}: {exc}",
            file=sys.stderr,
        )
