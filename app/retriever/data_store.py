"""
app.retriever.data_store — Vector store retriever for scibot collections.

Public API
----------
DataStoreRetriever
    Unified retrieval class.  Wraps all supported vector store providers with
    a consistent search API and automatic filter normalisation.  All searches
    are scoped to a single user/collection pair.

get_retriever(username, collection_name, *, password, effective_cfg, ...)
    Factory function.  Returns a ``DataStoreRetriever`` for a user's
    collection.  Accepts either a user password (for config decryption) or a
    pre-resolved config dict.

build_filter(**kwargs) -> dict
    Convenience helper to build universal metadata filter dicts from keyword
    arguments.

Provider support
----------------
All six vector store providers are fully supported:

  chroma · pinecone · qdrant · milvus · mongodb · postgres

Filter syntax
-------------
All search methods accept an optional *filter* dict in a unified syntax
(MongoDB/Chroma-style) that is automatically normalised to each provider's
native format:

    Simple equality
        ``{"source_id": "arxiv:1706.03762"}``

    Comparison operators
        ``{"chunk_index": {"$gt": 3}}``
        ``{"chunk_index": {"$gte": 0, "$lte": 9}}``

    Set operators
        ``{"source_id": {"$in": ["arxiv:1234", "arxiv:5678"]}}``

    Logical operators
        ``{"$and": [{"username": "alice"}, {"collection_name": "papers"}]}``
        ``{"$or": [{"source_id": "arxiv:1234"}, {"source_id": "arxiv:5678"}]}``

    Use ``build_filter()`` to build these from keyword arguments:
        ``build_filter(username="alice", collection_name="papers")``
        → ``{"$and": [{"username": "alice"}, {"collection_name": "papers"}]}``
"""

from __future__ import annotations

import re as _re
from typing import Any

from langchain_core.documents import Document

from app.config.store import get_store

__all__ = ["DataStoreRetriever", "get_retriever", "build_filter"]


# ---------------------------------------------------------------------------
# Collection naming  (mirrors ingestion.py without the circular import)
# ---------------------------------------------------------------------------

_UNSAFE_CHARS = _re.compile(r"[^a-zA-Z0-9_]")


def _vector_collection_name(username: str, collection_name: str) -> str:
    """
    Return the sanitised vector store collection name for this user/collection.

    Format: ``{username}__{collection_name}``
    Non-[a-zA-Z0-9_] characters are replaced with ``_``.
    Truncated to 63 characters to stay within most provider limits.
    """
    raw = f"{username}__{collection_name}"
    return _UNSAFE_CHARS.sub("_", raw)[:63]


# ---------------------------------------------------------------------------
# Store construction
# ---------------------------------------------------------------------------

def _build_store(
    username: str,
    collection_name: str,
    effective_cfg: dict,
    embedding: Any | None = None,
) -> Any:
    """
    Build a LangChain vector store scoped to the given user/collection pair.

    Mirrors ``_store_for_collection`` in ``app.storage.ingestion`` but lives
    here to avoid a circular import.
    """
    vcname = _vector_collection_name(username, collection_name)
    store_cfg = dict(effective_cfg.get("store") or {})
    store_cfg["collection_name"] = vcname

    # Pinecone uses a namespace for sub-index isolation
    if store_cfg.get("provider") == "pinecone":
        store_cfg.setdefault("namespace", vcname)

    # Propagate embedding config when no pre-built instance is supplied
    embedding_cfg = effective_cfg.get("embedding")
    if embedding is None and embedding_cfg:
        store_cfg.setdefault("embedding", embedding_cfg)

    return get_store(store_cfg, embedding=embedding)


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

_CLASS_TO_PROVIDER: dict[str, str] = {
    "Chroma": "chroma",
    "PineconeVectorStore": "pinecone",
    "QdrantVectorStore": "qdrant",
    "Milvus": "milvus",
    "MongoDBAtlasVectorSearch": "mongodb",
    "PGVector": "postgres",
}


def _detect_provider(store: Any) -> str:
    """
    Return the canonical provider name for a LangChain vector store instance.

    Falls back to ``"unknown"`` when the class is not in the known registry.
    """
    return _CLASS_TO_PROVIDER.get(type(store).__name__, "unknown")


# ---------------------------------------------------------------------------
# Filter normalisation — one converter per provider
# ---------------------------------------------------------------------------

def _to_pinecone_filter(f: dict) -> dict:
    """
    Convert to Pinecone metadata filter format.

    Pinecone requires field-level operators: ``{"field": {"$eq": val}}``.
    Logical ``$and``/``$or`` are passed through; inner clauses are recursed.
    """
    if "$and" in f:
        return {"$and": [_to_pinecone_filter(sub) for sub in f["$and"]]}
    if "$or" in f:
        return {"$or": [_to_pinecone_filter(sub) for sub in f["$or"]]}
    return {key: (val if isinstance(val, dict) else {"$eq": val}) for key, val in f.items()}


def _to_qdrant_filter(f: dict) -> Any:
    """
    Convert to a ``qdrant_client.models.Filter`` object.

    Raises ``ImportError`` if ``qdrant-client`` is not installed.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range

    def _convert(node: dict) -> Any:
        if "$and" in node:
            return Filter(must=[_convert(sub) for sub in node["$and"]])
        if "$or" in node:
            return Filter(should=[_convert(sub) for sub in node["$or"]])

        must: list = []
        must_not: list = []
        for key, val in node.items():
            if isinstance(val, dict):
                ops = set(val)
                if "$eq" in ops:
                    must.append(FieldCondition(key=key, match=MatchValue(value=val["$eq"])))
                elif "$ne" in ops:
                    must_not.append(FieldCondition(key=key, match=MatchValue(value=val["$ne"])))
                elif "$in" in ops:
                    must.append(FieldCondition(key=key, match=MatchAny(any=val["$in"])))
                elif "$nin" in ops:
                    must_not.append(FieldCondition(key=key, match=MatchAny(any=val["$nin"])))
                elif ops & {"$gt", "$gte", "$lt", "$lte"}:
                    rng: dict = {}
                    for op, rk in (("$gt", "gt"), ("$gte", "gte"), ("$lt", "lt"), ("$lte", "lte")):
                        if op in val:
                            rng[rk] = val[op]
                    must.append(FieldCondition(key=key, range=Range(**rng)))
                else:
                    # Unknown operator dict — treat as exact match on the dict value
                    must.append(FieldCondition(key=key, match=MatchValue(value=val)))
            else:
                must.append(FieldCondition(key=key, match=MatchValue(value=val)))
        return Filter(
            must=must or None,
            must_not=must_not or None,
        )

    return _convert(f)


def _to_milvus_expr(f: dict) -> str:
    """Convert to a Milvus boolean expression string (SQL-like syntax)."""

    def _val(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
        return str(v)

    def _convert(node: dict) -> str:
        if "$and" in node:
            return " && ".join(f"({_convert(sub)})" for sub in node["$and"])
        if "$or" in node:
            return " || ".join(f"({_convert(sub)})" for sub in node["$or"])

        parts: list[str] = []
        for key, val in node.items():
            if isinstance(val, dict):
                for op, mval in val.items():
                    if op == "$eq":
                        parts.append(f"{key} == {_val(mval)}")
                    elif op == "$ne":
                        parts.append(f"{key} != {_val(mval)}")
                    elif op == "$gt":
                        parts.append(f"{key} > {_val(mval)}")
                    elif op == "$gte":
                        parts.append(f"{key} >= {_val(mval)}")
                    elif op == "$lt":
                        parts.append(f"{key} < {_val(mval)}")
                    elif op == "$lte":
                        parts.append(f"{key} <= {_val(mval)}")
                    elif op == "$in":
                        items = ", ".join(_val(v) for v in mval)
                        parts.append(f"{key} in [{items}]")
                    elif op == "$nin":
                        items = ", ".join(_val(v) for v in mval)
                        parts.append(f"{key} not in [{items}]")
            else:
                parts.append(f"{key} == {_val(val)}")
        return " && ".join(parts)

    return _convert(f)


def _normalize_filter(raw_filter: dict | None, provider: str) -> dict[str, Any]:
    """
    Convert a universal filter dict to provider-native keyword arguments.

    Returns a dict that can be unpacked directly into store search calls::

        store.similarity_search(query, k=k, **_normalize_filter(f, provider))

    Provider mapping
    ----------------
    chroma / postgres   → ``{"filter": raw_filter}``  (supported natively)
    pinecone            → ``{"filter": <pinecone_format>}``
    qdrant              → ``{"filter": <qdrant_client.models.Filter>}``
    milvus              → ``{"expr": "<sql_expression>"}``
    mongodb             → ``{"pre_filter": raw_filter}``  (kwarg name differs)
    unknown             → ``{"filter": raw_filter}``  (best-effort)
    """
    if not raw_filter:
        return {}

    if provider == "milvus":
        return {"expr": _to_milvus_expr(raw_filter)}

    if provider == "mongodb":
        return {"pre_filter": raw_filter}

    if provider == "pinecone":
        return {"filter": _to_pinecone_filter(raw_filter)}

    if provider == "qdrant":
        return {"filter": _to_qdrant_filter(raw_filter)}

    # chroma, postgres, unknown — pass through as-is
    return {"filter": raw_filter}


# ---------------------------------------------------------------------------
# Public filter builder
# ---------------------------------------------------------------------------

def build_filter(**kwargs: Any) -> dict:
    """
    Build a universal metadata filter dict from keyword arguments.

    Zero kwargs
        Returns ``{}`` — no filter (matches all documents).

    Single kwarg
        Returns ``{"key": "value"}`` — exact-match filter on one field.

    Multiple kwargs
        Returns ``{"$and": [{"key1": val1}, {"key2": val2}, ...]}`` —
        all conditions must match.

    For richer filters (comparison, ``$in``, ``$or``), construct the dict
    directly using the operators described in the module docstring.

    Common metadata fields stored on every ingested chunk
    ------------------------------------------------------
    source_id        e.g. ``"arxiv:1706.03762"``, ``"youtube:dQw4w9WgXcQ"``
    username         e.g. ``"alice"``
    collection_name  e.g. ``"papers"``
    vector_collection  e.g. ``"alice__papers"``
    ingested_at      ISO-8601 UTC string, e.g. ``"2026-03-16T12:00:00Z"``
    source_type      e.g. ``"paper"``, ``"youtube"``, ``"webpage"``
    title            document title (when available)
    chunk_index      0-based position within the parent document
    chunk_count      total number of chunks from the parent document

    Examples
    --------
    >>> build_filter(source_id="arxiv:1706.03762")
    {'source_id': 'arxiv:1706.03762'}

    >>> build_filter(username="alice", collection_name="papers")
    {'$and': [{'username': 'alice'}, {'collection_name': 'papers'}]}

    >>> build_filter()
    {}
    """
    if not kwargs:
        return {}
    if len(kwargs) == 1:
        k, v = next(iter(kwargs.items()))
        return {k: v}
    return {"$and": [{k: v} for k, v in kwargs.items()]}


# ---------------------------------------------------------------------------
# Config merging helper  (local copy — avoids importing from users.config)
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# DataStoreRetriever
# ---------------------------------------------------------------------------

class DataStoreRetriever:
    """
    Unified retriever for scibot vector stores.

    Provides similarity search, MMR search, and score-threshold search across
    all six supported vector store providers: Chroma, Pinecone, Qdrant,
    Milvus, MongoDB Atlas, and PostgreSQL/pgvector.

    Metadata filters use a unified dict syntax (MongoDB/Chroma-style) that is
    automatically normalised to each provider's native format.  Use
    ``build_filter()`` to construct filter dicts from keyword arguments.

    The underlying LangChain vector store is initialised **lazily** on the
    first search call — constructing a ``DataStoreRetriever`` opens no
    network connections.

    Do **not** instantiate directly.  Use ``get_retriever()`` instead.

    Parameters
    ----------
    username        : User who owns the collection.
    collection_name : Logical collection name (e.g. ``"papers"``).
    effective_cfg   : Resolved configuration dict (from ``resolve_config``).
    embedding       : Optional pre-built embedding instance.  When provided
                      the ``"embedding"`` section of ``effective_cfg`` is
                      ignored.
    """

    def __init__(
        self,
        username: str,
        collection_name: str,
        effective_cfg: dict,
        *,
        embedding: Any | None = None,
    ) -> None:
        self.username = username
        self.collection_name = collection_name
        self._effective_cfg = effective_cfg
        self._embedding = embedding
        self._store: Any | None = None
        self._provider: str | None = None

    def __repr__(self) -> str:
        provider = self._provider or "<lazy>"
        return (
            f"DataStoreRetriever("
            f"username={self.username!r}, "
            f"collection={self.collection_name!r}, "
            f"provider={provider!r})"
        )

    # ── Lazy store / provider ─────────────────────────────────────────────────

    @property
    def store(self) -> Any:
        """
        The underlying LangChain vector store instance.

        Initialised lazily on first access; subsequent accesses return the
        cached instance.
        """
        if self._store is None:
            self._store = _build_store(
                self.username,
                self.collection_name,
                self._effective_cfg,
                self._embedding,
            )
        return self._store

    @property
    def provider(self) -> str:
        """
        The vector store provider name (e.g. ``"chroma"``, ``"qdrant"``).

        Resolved on first access (triggers lazy ``store`` init).
        """
        if self._provider is None:
            self._provider = _detect_provider(self.store)
        return self._provider

    # ── Core search methods ───────────────────────────────────────────────────

    def search(
        self,
        query: str,
        k: int = 4,
        filter: dict | None = None,
        search_type: str = "similarity",
        score_threshold: float | None = None,
        fetch_k: int = 20,
        lambda_mult: float = 0.5,
    ) -> list[Document]:
        """
        Search the vector store and return the top-``k`` matching Documents.

        Parameters
        ----------
        query           : Natural language query text.
        k               : Number of documents to return.
        filter          : Metadata filter dict (universal syntax).  Use
                          ``build_filter()`` to construct this.
        search_type     : One of:

                          - ``"similarity"`` *(default)* — standard
                            nearest-neighbour search.
                          - ``"mmr"`` — Maximal Marginal Relevance; trades
                            some relevance for result diversity.
                          - ``"similarity_score_threshold"`` — similarity
                            search with a minimum relevance score cutoff.
                            Set ``score_threshold`` to eliminate low-quality
                            results.

        score_threshold : Minimum relevance score in [0, 1].  Only applied
                          when *search_type* is
                          ``"similarity_score_threshold"``.
        fetch_k         : Candidate pool size for MMR re-ranking.  Only
                          used when *search_type* is ``"mmr"``.
        lambda_mult     : MMR diversity parameter in [0, 1].  0 = maximum
                          diversity, 1 = maximum relevance.  Only used with
                          ``"mmr"``.

        Returns
        -------
        list[Document]
            Matching documents ordered by relevance (highest first).

        Raises
        ------
        ValueError  If *search_type* is not one of the supported values.
        """
        filter_kwargs = _normalize_filter(filter, self.provider)

        if search_type == "similarity":
            return self.store.similarity_search(query, k=k, **filter_kwargs)

        if search_type == "mmr":
            return self.store.max_marginal_relevance_search(
                query,
                k=k,
                fetch_k=fetch_k,
                lambda_mult=lambda_mult,
                **filter_kwargs,
            )

        if search_type == "similarity_score_threshold":
            pairs: list[tuple[Document, float]] = (
                self.store.similarity_search_with_relevance_scores(query, k=k, **filter_kwargs)
            )
            if score_threshold is None:
                return [doc for doc, _ in pairs]
            return [doc for doc, score in pairs if score >= score_threshold]

        raise ValueError(
            f"Unknown search_type {search_type!r}. "
            "Valid values: 'similarity', 'mmr', 'similarity_score_threshold'."
        )

    def search_with_scores(
        self,
        query: str,
        k: int = 4,
        filter: dict | None = None,
    ) -> list[tuple[Document, float]]:
        """
        Search the vector store and return ``(Document, score)`` pairs.

        Scores are **raw provider values** and are not normalised to a common
        range:

        - **Chroma**: cosine distance (lower = more similar; 0–2).
        - **Pinecone / Qdrant / MongoDB / pgvector**: cosine similarity
          (higher = more similar; typically 0–1).
        - **Milvus**: depends on the index metric configured at collection
          creation time.

        For normalised relevance scores use
        ``search(search_type='similarity_score_threshold')`` instead.

        Parameters
        ----------
        query   : Natural language query text.
        k       : Number of results to return.
        filter  : Metadata filter dict (universal syntax).

        Returns
        -------
        list[tuple[Document, float]]
            Pairs of ``(document, raw_score)``, ordered by score.
        """
        filter_kwargs = _normalize_filter(filter, self.provider)
        return self.store.similarity_search_with_score(query, k=k, **filter_kwargs)

    def mmr_search(
        self,
        query: str,
        k: int = 4,
        fetch_k: int = 20,
        lambda_mult: float = 0.5,
        filter: dict | None = None,
    ) -> list[Document]:
        """
        Maximal Marginal Relevance search — balances relevance and diversity.

        On each step, selects the document that is most relevant to the query
        while being least similar to the documents already selected.

        Parameters
        ----------
        query       : Natural language query text.
        k           : Number of documents to return.
        fetch_k     : Size of the initial candidate pool (should be ≥ ``k``).
        lambda_mult : 0 → maximise diversity · 1 → maximise relevance.
        filter      : Metadata filter dict (universal syntax).

        Returns
        -------
        list[Document]
        """
        return self.search(
            query,
            k=k,
            filter=filter,
            search_type="mmr",
            fetch_k=fetch_k,
            lambda_mult=lambda_mult,
        )

    # ── LangChain chain integration ───────────────────────────────────────────

    def as_retriever(
        self,
        search_type: str = "similarity",
        k: int = 4,
        score_threshold: float | None = None,
        filter: dict | None = None,
        fetch_k: int = 20,
        lambda_mult: float = 0.5,
    ) -> Any:
        """
        Return a LangChain ``VectorStoreRetriever`` for use in LCEL chains.

        The returned object implements ``.invoke(query)`` and can be composed
        with prompts and LLMs using the ``|`` pipe operator::

            retriever = get_retriever("alice", "papers", password="pw")
            chain = retriever.as_retriever() | prompt | llm
            answer = chain.invoke("What is multi-head attention?")

        Parameters
        ----------
        search_type     : ``"similarity"``, ``"mmr"``, or
                          ``"similarity_score_threshold"``.
        k               : Number of documents to retrieve per query.
        score_threshold : Score cutoff for ``"similarity_score_threshold"``
                          mode (0–1; higher = stricter).
        filter          : Metadata filter dict (universal syntax).
        fetch_k         : MMR candidate pool size (only used for ``"mmr"``).
        lambda_mult     : MMR diversity parameter (only used for ``"mmr"``).

        Returns
        -------
        langchain_core.vectorstores.VectorStoreRetriever
        """
        filter_kwargs = _normalize_filter(filter, self.provider)
        search_kwargs: dict[str, Any] = {"k": k, **filter_kwargs}

        if search_type == "similarity_score_threshold" and score_threshold is not None:
            search_kwargs["score_threshold"] = score_threshold

        if search_type == "mmr":
            search_kwargs["fetch_k"] = fetch_k
            search_kwargs["lambda_mult"] = lambda_mult

        return self.store.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_retriever(
    username: str,
    collection_name: str,
    *,
    password: str | None = None,
    effective_cfg: dict | None = None,
    override: dict | None = None,
    embedding: Any | None = None,
) -> DataStoreRetriever:
    """
    Build and return a :class:`DataStoreRetriever` for a user's collection.

    Two mutually exclusive ways to supply configuration:

    **1. By password** (most common — used by agents and tools)::

        retriever = get_retriever("alice", "papers", password="alice_pw")

    Calls :func:`app.users.config.resolve_config` to load and decrypt Alice's
    configuration from the database, merging it with environment defaults and
    any ``override`` supplied.

    **2. By pre-resolved config** (when config is already on hand)::

        cfg = resolve_config("alice", "alice_pw", override=None)
        retriever = get_retriever("alice", "papers", effective_cfg=cfg)

    The ``_store`` is initialised lazily — this function opens no connections.

    Parameters
    ----------
    username        : User who owns the collection.
    collection_name : Logical collection name (e.g. ``"papers"``).
    password        : User's password.  Required when ``effective_cfg`` is
                      not provided.
    effective_cfg   : Pre-resolved config dict.  When provided, ``password``
                      is not used (but ``override`` is still merged on top).
    override        : Config dict deep-merged on top of the resolved config.
                      Can force a specific provider, model, or connection
                      setting.
    embedding       : Pre-built LangChain Embeddings instance.  When
                      provided, the ``"embedding"`` section of the resolved
                      config is ignored and this instance is used directly.

    Returns
    -------
    DataStoreRetriever

    Raises
    ------
    ValueError
        If neither ``password`` nor ``effective_cfg`` is supplied.
    AuthError
        If ``password`` is supplied but authentication fails (propagated from
        :func:`app.users.config.resolve_config`).

    Examples
    --------
    Basic similarity search::

        retriever = get_retriever("alice", "papers", password="pw")
        docs = retriever.search("multi-head attention", k=5)

    Filtered search::

        f = build_filter(source_id="arxiv:1706.03762")
        docs = retriever.search("attention mechanism", k=10, filter=f)

    LangChain LCEL chain::

        r = get_retriever("alice", "papers", password="pw")
        chain = r.as_retriever(k=6) | prompt | llm
        answer = chain.invoke("Explain self-attention.")

    MMR (diverse results)::

        docs = retriever.mmr_search("transformers", k=6, lambda_mult=0.4)

    Score-threshold search (drop low-quality chunks)::

        docs = retriever.search(
            "attention mechanism",
            search_type="similarity_score_threshold",
            score_threshold=0.6,
        )
    """
    if effective_cfg is not None:
        cfg = _deep_merge(effective_cfg, override) if override else dict(effective_cfg)
    elif password is not None:
        from app.users.config import resolve_config
        cfg = resolve_config(username, password, override)
    else:
        raise ValueError(
            "get_retriever() requires either 'password' or 'effective_cfg'. "
            "Provide the user's password to decrypt their configuration, or "
            "supply a pre-resolved config dict via 'effective_cfg'."
        )

    return DataStoreRetriever(username, collection_name, cfg, embedding=embedding)
