# Collections

A collection groups any combination of sources under a single name for a user. `collection.py` handles loading, persistence, and lifecycle. Ingesting into the vector store is a separate step — see [app/storage/README.md](../storage/README.md).

## Typical workflow

```python
from app.sources.collection import create_collection, update_collection
from app.storage import ingest_collection, ingest_new_sources

# 1. Create — loads all sources, saves Documents to disk and metadata to DB
result = create_collection("alice", "my-papers", sources={
    "papers": [
        {"url_or_path": "https://arxiv.org/abs/1706.03762", "fetch_references": True},
        {"url_or_path": "https://pubmed.ncbi.nlm.nih.gov/12345678"},
    ],
    "youtube": [{"url": "https://youtu.be/dQw4w9WgXcQ"}],
    "github":  [{"url": "https://github.com/karpathy/nanoGPT"}],
})

# 2. Ingest — chunk and write to vector store
ingest_collection("alice", "my-papers")

# 3. Later: add new sources
update_collection("alice", "my-papers", new_sources={
    "webpages": [{"url": "https://example.com/blog-post"}],
})

# 4. Ingest only what's new
ingest_new_sources("alice", "my-papers")
```

## Public API

| Function | Purpose |
|---|---|
| `create_collection(username, collection_name, sources, config, password)` | Load all sources, write pkl files, save collection to DB. |
| `list_collections(username)` | Return list of collection metadata dicts for a user. |
| `get_collection(username, collection_name)` | Return the full collection data dict from DB. |
| `update_collection(username, collection_name, new_sources, config, password)` | Load new sources, append pkl files, update DB. |
| `delete_collection(username, collection_name)` | Remove pkl files, DB record, and vector store entries. |
| `reload_collection(username, collection_name, config, password)` | Re-download all sources from scratch, replacing existing pkl files. |

All write functions return a `CollectionResult`:

```python
{"loaded": 3, "failed": 0, "errors": []}
```

## Source types

Pass any combination of these keys in `sources` / `new_sources`:

```python
{
    "papers": [
        {
            "url_or_path":     "arxiv:1706.03762",  # arXiv URL/ID, PubMed URL/PMID, or local file
            "source_type":     "arxiv",             # auto-detected if omitted
            "fetch_references": True,
            "reference_depth": 2,
            "reference_top_n": 10,
        }
    ],
    "youtube":      [{"url": "https://youtu.be/…", "language": ["en"]}],
    "github":       [{"url": "https://github.com/owner/repo", "branch": "main"}],
    "webpages":     [{"url": "https://…", "crawl": False, "max_depth": 2}],
    "videos":       [{"file_path": "/path/to/lecture.mp4"}],
    "audios":       [{"file_path": "/path/to/talk.mp3", "model_size": "base"}],
    "images":       [{"file_path": "/path/to/fig.png", "description": "optional caption"}],
    "dynamic_sources": [...],
}
```

`source_type` for papers is auto-detected from the URL/path if omitted (`"arxiv"` | `"pubmed"` | `"pdf"` | `"latex"` | `"markdown"`).

## Document storage

Loaded documents are pickled individually to disk:

```
app/data/{username}/{collection_name}/documents/doc_0001.pkl
app/data/{username}/{collection_name}/documents/doc_0002.pkl
...
```

Each file holds exactly one `langchain_core.documents.Document`. Sequential numbering allows safe appending via `update_collection`.

## Source tracking fields

Every source entry stored in the DB carries:

| Field | Value |
|---|---|
| `source_id` | Stable identifier used by the ingestion layer (e.g. `arxiv:1706.03762`) |
| `doc_paths` | Absolute paths to the pkl files for this source |
| `ingested_at` | ISO-8601 UTC timestamp set after vectors are written; `null` if not yet ingested |

The ingestion layer uses `ingested_at` to determine which sources need ingesting (`ingest_new_sources` skips any entry where this is not null).

## Parallel loading

Sources are loaded concurrently with `ThreadPoolExecutor(max_workers=4)`. Per-source errors are captured and returned in `CollectionResult["errors"]` without aborting the whole collection.
