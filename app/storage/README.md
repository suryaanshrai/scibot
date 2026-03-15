# Ingestion

Vector store ingestion for scibot collections.  
Ingestion is a **separate, explicit step** from source loading — load your sources first (via `app.sources.collection`), then call one of the functions below.

## Quick start

```python
from app.storage import (
    ingest_collection,
    ingest_new_sources,
    update_store,
    delete_collection_vectors,
    check_reingest_required,
    StoreSettingsDriftError,
)

# First ingest after create_collection()
result = ingest_collection("alice", "my-papers")
print(result["total_chunks"], "chunks written")

# Incremental ingest after update_collection() — skips already-ingested sources
result = ingest_new_sources("alice", "my-papers")

# Re-ingest specific updated sources by source_id
result = update_store("alice", "my-papers", source_ids=["arxiv:1706.03762"])
```

## Public API

| Function | Purpose |
|---|---|
| `ingest_collection(username, collection_name)` | Ingest **all** sources in a collection. Use after `create_collection` or to rebuild fully. |
| `ingest_new_sources(username, collection_name)` | Ingest only sources where `ingested_at` is null. Safe to call repeatedly — no-op when everything is up to date. |
| `update_store(username, collection_name, source_ids)` | Delete and re-ingest specific sources by `source_id`. Use after `update_collection`. |
| `delete_collection_vectors(username, collection_name)` | Remove all vectors for a collection from the store. Required before changing store settings. |
| `check_reingest_required(username, collection_name, config)` | Non-raising check: returns `{"reingest_required": bool, "changed_settings": [...]}`. |

All ingest functions return an `IngestResult`:

```python
{
    "username":        "alice",
    "collection_name": "my-papers",
    "ingested_sources": 3,   # source entries processed this call
    "total_chunks":    142,  # vector chunks written
    "errors":          [],   # non-fatal per-source error messages
}
```

## Configuration

Pass a `config` dict to override the user's stored config:

```python
ingest_collection("alice", "my-papers", config={
    "store": {
        "provider":          "chroma",
        "distance_function": "cosine",  # "cosine" | "l2" | "ip"
        "host":              "localhost",
        "port":              8000,
    },
    "embedding": {
        "provider": "huggingface",
        "model":    "sentence-transformers/all-MiniLM-L6-v2",
    },
})
```

## Settings drift

Store settings (distance function, embedding model, etc.) **cannot change** after the first ingest without a full rebuild — mixing vectors from different embedding spaces produces meaningless similarity results.

Any ingest call will raise `StoreSettingsDriftError` if settings have changed since the last ingest:

```python
try:
    ingest_collection("alice", "my-papers", config={"store": {"distance_function": "l2"}})
except StoreSettingsDriftError as e:
    print(e.changed_settings)
    # [{"key": "distance_function", "was": "cosine", "now": "l2"}]
```

**To apply new settings:**

```python
# 1. Check what will change (optional — for UI warnings)
result = check_reingest_required("alice", "my-papers", config={...})
if result["reingest_required"]:
    # show warning to user

# 2. Wipe old vectors, then rebuild
delete_collection_vectors("alice", "my-papers")
ingest_collection("alice", "my-papers", config={...})
```

## Chunking

- **Prose** (papers, web pages, markdown): `RecursiveCharacterTextSplitter`, 800 tokens / 150 overlap.
- **Code** (GitHub repos): Language-aware splitter, detected by file extension.

Every chunk carries the full original source metadata (`source_id`, `title`, `authors`, `arxiv_id`, `pmid`, `source_url`, …) plus `username`, `collection_name`, `vector_collection`, `ingested_at`, `chunk_index`, `chunk_count`.

## Vector collection naming

Collections are namespaced per user: `{username}__{collection_name}`, with non-alphanumeric characters replaced by `_`, truncated to 63 characters.
