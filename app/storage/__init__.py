"""
app.storage — vector store ingestion service.

Public API
----------
ingest_documents(docs, username, collection_name, ...)    -> IngestResult
    Low-level: split, enrich, and write an arbitrary list of Documents to
    the configured vector store.

ingest_collection(username, collection_name, ...)         -> IngestResult
    Ingest ALL source entries in an existing collection.  Automatically
    (re-)loads pkl files for any source whose disk files are missing.
    Raises ``StoreSettingsDriftError`` if the store config has changed
    since the last ingest (call ``delete_collection_vectors`` first).

ingest_new_sources(username, collection_name, ...)        -> IngestResult
    Ingest only source entries whose ``ingested_at`` is ``null``.  Safe to
    call repeatedly — no-op when everything is already ingested.
    Raises ``StoreSettingsDriftError`` on config drift (same as above).

update_store(username, collection_name, source_ids, ...)  -> IngestResult
    Re-ingest specific sources by their ``source_id``.  Deletes existing
    vectors for those sources first, then re-ingests.
    Raises ``StoreSettingsDriftError`` on config drift (same as above).

check_reingest_required(username, collection_name, ...)   -> dict
    Non-raising drift check.  Returns
    ``{"reingest_required": bool, "changed_settings": [...]}``.  Call this
    before saving new user config to surface a warning in the UI/API.

delete_collection_vectors(username, collection_name, ...) -> None
    Remove all vectors for a collection from the vector store.
    Must be called before re-ingesting with changed store settings.

IngestResult
    TypedDict: collection_name, username, ingested_sources, total_chunks,
    errors.

StoreSettingsDriftError
    Exception raised when the store config (distance function, embedding
    model/provider) has changed since the last ingest.  Carries
    ``changed_settings`` list and a human-readable explanation.
"""

from app.storage.ingestion import (
    IngestResult,
    StoreSettingsDriftError,
    check_reingest_required,
    delete_collection_vectors,
    ingest_collection,
    ingest_documents,
    ingest_new_sources,
    update_store,
)

__all__ = [
    "IngestResult",
    "StoreSettingsDriftError",
    "ingest_documents",
    "ingest_collection",
    "ingest_new_sources",
    "update_store",
    "check_reingest_required",
    "delete_collection_vectors",
]
