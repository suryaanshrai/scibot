# `app/retriever` — Vector Store Retriever

Retrieves relevant chunks from a user's ingested collection. Works with all
six vector store providers supported by scibot (Chroma, Pinecone, Qdrant,
Milvus, MongoDB Atlas, PostgreSQL/pgvector).

---

## Quick start

```python
from app.retriever.data_store import get_retriever, build_filter

# Build a retriever (decrypts the user's config from the DB)
retriever = get_retriever("alice", "papers", password="alice_pw")

# Simple similarity search
docs = retriever.search("multi-head attention mechanism", k=5)

# With a metadata filter
docs = retriever.search(
    "transformer architecture",
    k=5,
    filter=build_filter(source_id="arxiv:1706.03762"),
)
```

---

## `get_retriever()`

```python
get_retriever(
    username,
    collection_name,
    *,
    password=None,       # decrypt user config from DB
    effective_cfg=None,  # OR pass a pre-resolved config dict
    override=None,       # dict deep-merged on top of the resolved config
    embedding=None,      # pre-built LangChain Embeddings instance
) -> DataStoreRetriever
```

Two ways to supply config:

| Use case | How |
|---|---|
| Normal agent/tool use | `password="..."` — config is decrypted from the DB |
| Config already on hand | `effective_cfg=resolve_config(...)` — skip DB lookup |

The underlying vector store connection is opened **lazily** — `get_retriever()`
itself makes no network calls.

---

## Search methods

### `search()` — unified entry point

```python
docs = retriever.search(
    query,
    k=4,
    filter=None,
    search_type="similarity",   # "similarity" | "mmr" | "similarity_score_threshold"
    score_threshold=None,       # float 0–1, used with "similarity_score_threshold"
    fetch_k=20,                 # MMR candidate pool size
    lambda_mult=0.5,            # MMR diversity: 0=max diversity, 1=max relevance
)
```

### `search_with_scores()` — raw scores

```python
pairs = retriever.search_with_scores(query, k=4, filter=None)
# → list[tuple[Document, float]]
```

Note: score semantics differ by provider (Chroma returns distance, others
return similarity). For normalised 0–1 scores use
`search_type="similarity_score_threshold"`.

### `mmr_search()` — diverse results

```python
docs = retriever.mmr_search(
    query, k=4, fetch_k=20, lambda_mult=0.4, filter=None
)
```

### `as_retriever()` — LangChain chain integration

```python
lc_retriever = retriever.as_retriever(
    search_type="similarity",   # or "mmr" / "similarity_score_threshold"
    k=4,
    score_threshold=0.5,        # only used with "similarity_score_threshold"
    filter=None,
    fetch_k=20,
    lambda_mult=0.5,
)

# Drop into an LCEL chain
chain = lc_retriever | prompt | llm
answer = chain.invoke("Explain self-attention.")
```

---

## Metadata filters

All search methods accept a `filter` dict in a unified syntax that is
automatically translated to each provider's native format.

```python
from app.retriever.data_store import build_filter

# Single field
build_filter(source_id="arxiv:1706.03762")
# → {"source_id": "arxiv:1706.03762"}

# Multiple fields — joined with $and
build_filter(username="alice", collection_name="papers")
# → {"$and": [{"username": "alice"}, {"collection_name": "papers"}]}

# No filter (matches everything)
build_filter()
# → {}
```

For richer conditions, construct the dict directly:

```python
# Comparison
{"chunk_index": {"$gt": 0}}

# Set membership
{"source_id": {"$in": ["arxiv:1234", "arxiv:5678"]}}

# Logical OR
{"$or": [{"source_id": "arxiv:1234"}, {"source_id": "arxiv:5678"}]}
```

**Common metadata fields** on every ingested chunk:

| Field | Example |
|---|---|
| `source_id` | `"arxiv:1706.03762"`, `"youtube:dQw4w9WgXcQ"` |
| `username` | `"alice"` |
| `collection_name` | `"papers"` |
| `vector_collection` | `"alice__papers"` |
| `ingested_at` | `"2026-03-16T12:00:00Z"` |
| `chunk_index` | `0` (0-based position within parent doc) |
| `chunk_count` | total chunks from the same source document |
| `title` | document title (when available) |
| `source_type` | `"paper"`, `"youtube"`, `"webpage"`, … |

---

## Using a custom provider or embedding

```python
# Force Qdrant for this retrieval (overrides user config)
retriever = get_retriever(
    "alice", "papers",
    password="alice_pw",
    override={
        "store": {"provider": "qdrant", "qdrant_url": "http://localhost:6333"},
    },
)

# Inject a pre-built embedding (skips building one from config)
from langchain_huggingface import HuggingFaceEmbeddings
emb = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
retriever = get_retriever("alice", "papers", password="pw", embedding=emb)
```
