"""
Vector store configuration — registry, factory, and listing.

Usage:
    from app.config.store import get_store, list_stores

    # Default (from env), embedding built automatically
    store = get_store()

    # Explicit config
    store = get_store({
        "provider": "qdrant",
        "collection_name": "my_docs",
        "qdrant_url": "http://localhost:6333",
    })

    # Pass a pre-built embedding model
    from app.config.embedding_model import get_embedding_model
    embedding = get_embedding_model({"provider": "openai"})
    store = get_store({"provider": "chroma"}, embedding=embedding)
"""

from __future__ import annotations

import importlib.util
from typing import Any

from app.config.settings import (
    CHROMA_HOST,
    CHROMA_PERSIST_DIRECTORY,
    CHROMA_PORT,
    DEFAULT_STORE_COLLECTION,
    DEFAULT_STORE_NAMESPACE,
    DEFAULT_STORE_PROVIDER,
    MILVUS_URI,
    MONGODB_CONNECTION_STRING,
    MONGODB_DATABASE_NAME,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    POSTGRES_CONNECTION_STRING,
    QDRANT_API_KEY,
    QDRANT_URL,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Maps provider identifier → importable package (internal; not exposed to callers).
_STORE_PACKAGES: dict[str, str] = {
    "chroma": "langchain_chroma",
    "pinecone": "langchain_pinecone",
    "qdrant": "langchain_qdrant",
    "milvus": "langchain_milvus",
    "mongodb": "langchain_mongodb",
    "postgres": "langchain_postgres",
}

_STORE_REGISTRY: list[dict[str, Any]] = [
    {
        "provider": "chroma",
        "human_name": "Chroma",
        "description": (
            "Lightweight in-process or client/server vector database. "
            "Runs in-memory, on disk, or as a remote service."
        ),
    },
    {
        "provider": "pinecone",
        "human_name": "Pinecone",
        "description": (
            "Fully managed, cloud-native vector database. "
            "Supports namespaces, metadata filtering, and hybrid search."
        ),
    },
    {
        "provider": "qdrant",
        "human_name": "Qdrant",
        "description": (
            "Open-source vector database with extended filtering and on-disk indexing. "
            "Runs in-memory, on disk, or as a remote service."
        ),
    },
    {
        "provider": "milvus",
        "human_name": "Milvus",
        "description": (
            "Distributed, cloud-native vector database built for billion-scale similarity search. "
            "Lite mode (Milvus Lite) embeds directly via a local file."
        ),
    },
    {
        "provider": "mongodb",
        "human_name": "MongoDB Atlas",
        "description": (
            "MongoDB Atlas Vector Search — add semantic search to your existing MongoDB Atlas cluster "
            "without a separate vector store."
        ),
    },
    {
        "provider": "postgres",
        "human_name": "PostgreSQL (pgvector)",
        "description": (
            "PostgreSQL with the pgvector extension. "
            "Ideal when you already run Postgres and want vector search without a separate service."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_available(provider: str) -> bool:
    pkg = _STORE_PACKAGES.get(provider)
    return pkg is not None and importlib.util.find_spec(pkg) is not None


def _get_registry_entry(provider: str) -> dict[str, Any]:
    for entry in _STORE_REGISTRY:
        if entry["provider"] == provider:
            return entry
    supported = [e["provider"] for e in _STORE_REGISTRY]
    raise ValueError(
        f"Unsupported store provider: '{provider}'. "
        f"Supported providers: {supported}"
    )


def _build_embedding(config: dict[str, Any] | None) -> Any:
    """Build an embedding model from the 'embedding' sub-key in config."""
    from app.config.embedding_model import get_embedding_model

    return get_embedding_model(config)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_store(
    config: dict[str, Any] | None = None,
    embedding: Any | None = None,
) -> Any:
    """
    Return an initialised LangChain vector store, ready to use.

    Parameters
    ----------
    config : dict, optional
        Top-level keys (all optional, fall back to env vars):
          provider         – store provider (default: env DEFAULT_STORE_PROVIDER)
          collection_name  – collection / index name (default: env DEFAULT_STORE_COLLECTION)
          namespace        – namespace inside the collection (Pinecone, Qdrant, etc.)
          embedding        – dict passed to get_embedding_model() to build the embedding
                             automatically (ignored when `embedding` arg is supplied)

        Chroma-specific:
          persist_directory – local path to persist on disk (omit for in-memory)
          chroma_host        – HTTP host for remote Chroma server
          chroma_port        – HTTP port for remote Chroma server
          distance_function  – HNSW distance metric: "cosine" (default), "l2", or "ip"

        Pinecone-specific:
          pinecone_api_key   – Pinecone API key
          pinecone_index_name – index name

        Qdrant-specific:
          qdrant_url         – Qdrant server URL (omit for in-memory)
          qdrant_api_key     – Qdrant API key

        Milvus-specific:
          milvus_uri         – URI, e.g. "./milvus.db" or "http://host:19530"
          drop_old           – bool; drop existing collection before creating (default: False)
          index_params       – dict; custom Milvus index build parameters

        MongoDB-specific:
          mongodb_connection_string – MongoDB Atlas connection URI
          mongodb_database_name     – database name

        Postgres-specific:
          postgres_connection_string – libpq-style connection string
          distance_strategy          – "cosine" (default), "euclidean", or "max_inner_product"

        extra_kwargs – dict; any additional keyword arguments passed directly to the
                       store constructor, merged last (can override named params)

    embedding : LangChain Embeddings instance, optional
        A pre-built embedding model. When provided, the 'embedding' key
        in `config` is ignored.
    """
    cfg = config or {}

    provider = cfg.get("provider") or DEFAULT_STORE_PROVIDER or "chroma"
    _get_registry_entry(provider)  # validate

    collection_name = cfg.get("collection_name") or DEFAULT_STORE_COLLECTION or "scibot"
    namespace = cfg.get("namespace") or DEFAULT_STORE_NAMESPACE or ""

    if embedding is None:
        embedding = _build_embedding(cfg.get("embedding"))
    extra_kwargs: dict[str, Any] = cfg.get("extra_kwargs") or {}

    # ── Chroma ────────────────────────────────────────────────────────────────
    if provider == "chroma":
        from langchain_chroma import Chroma

        chroma_host = cfg.get("chroma_host") or CHROMA_HOST
        if chroma_host:
            import chromadb

            chroma_port = int(cfg.get("chroma_port") or CHROMA_PORT or 8000)
            client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
            return Chroma(
                client=client,
                collection_name=collection_name,
                embedding_function=embedding,
                **extra_kwargs,
            )

        persist_dir = cfg.get("persist_directory") or CHROMA_PERSIST_DIRECTORY
        return Chroma(
            collection_name=collection_name,
            embedding_function=embedding,
            persist_directory=persist_dir or None,
            **extra_kwargs,
        )

    # ── Pinecone ──────────────────────────────────────────────────────────────
    if provider == "pinecone":
        from langchain_pinecone import PineconeVectorStore
        from pinecone import Pinecone

        api_key = cfg.get("pinecone_api_key") or PINECONE_API_KEY
        index_name = cfg.get("pinecone_index_name") or PINECONE_INDEX_NAME
        if not index_name:
            raise ValueError(
                "Pinecone requires an index name. "
                "Set 'pinecone_index_name' in config or PINECONE_INDEX_NAME in env."
            )

        pc = Pinecone(api_key=api_key)
        index = pc.Index(index_name)
        return PineconeVectorStore(
            index=index,
            embedding=embedding,
            namespace=namespace or None,
            **extra_kwargs,
        )

    # ── Qdrant ────────────────────────────────────────────────────────────────
    if provider == "qdrant":
        from langchain_qdrant import QdrantVectorStore
        from qdrant_client import QdrantClient

        qdrant_url = cfg.get("qdrant_url") or QDRANT_URL
        qdrant_api_key = cfg.get("qdrant_api_key") or QDRANT_API_KEY

        if qdrant_url:
            client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key or None)
        else:
            client = QdrantClient(":memory:")

        return QdrantVectorStore(
            client=client,
            collection_name=collection_name,
            embedding=embedding,
            **extra_kwargs,
        )

    # ── Milvus ────────────────────────────────────────────────────────────────
    if provider == "milvus":
        from langchain_milvus import Milvus

        milvus_uri = cfg.get("milvus_uri") or MILVUS_URI or "./milvus.db"
        milvus_kwargs: dict[str, Any] = {
            "embedding_function": embedding,
            "collection_name": collection_name,
            "connection_args": {"uri": milvus_uri},
        }
        if cfg.get("drop_old"):
            milvus_kwargs["drop_old"] = True
        if cfg.get("index_params"):
            milvus_kwargs["index_params"] = cfg["index_params"]
        milvus_kwargs.update(extra_kwargs)
        return Milvus(**milvus_kwargs)

    # ── MongoDB Atlas ─────────────────────────────────────────────────────────
    if provider == "mongodb":
        from langchain_mongodb import MongoDBAtlasVectorSearch
        from pymongo import MongoClient

        conn_str = cfg.get("mongodb_connection_string") or MONGODB_CONNECTION_STRING
        if not conn_str:
            raise ValueError(
                "MongoDB requires a connection string. "
                "Set 'mongodb_connection_string' in config or MONGODB_CONNECTION_STRING in env."
            )
        db_name = cfg.get("mongodb_database_name") or MONGODB_DATABASE_NAME or "scibot"

        client = MongoClient(conn_str)
        collection = client[db_name][collection_name]
        return MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embedding,
            index_name=collection_name,
            namespace=namespace or None,
            **extra_kwargs,
        )

    # ── Postgres (pgvector) ───────────────────────────────────────────────────
    if provider == "postgres":
        from langchain_postgres import PGVector
        from langchain_postgres.vectorstores import DistanceStrategy

        conn_str = cfg.get("postgres_connection_string") or POSTGRES_CONNECTION_STRING
        if not conn_str:
            raise ValueError(
                "Postgres requires a connection string. "
                "Set 'postgres_connection_string' in config or POSTGRES_CONNECTION_STRING in env."
            )
        _DISTANCE_MAP = {
            "cosine": DistanceStrategy.COSINE,
            "euclidean": DistanceStrategy.EUCLIDEAN,
            "max_inner_product": DistanceStrategy.MAX_INNER_PRODUCT,
        }
        distance_strategy = _DISTANCE_MAP.get(
            (cfg.get("distance_strategy") or "cosine").lower(),
            DistanceStrategy.COSINE,
        )
        return PGVector(
            embeddings=embedding,
            collection_name=collection_name,
            connection=conn_str,
            distance_strategy=distance_strategy,
            **extra_kwargs,
        )

    # Should never reach here — _get_registry_entry raises first
    raise ValueError(f"Unsupported store provider: '{provider}'")


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_stores() -> list[dict[str, Any]]:
    """
    Return all vector store providers whose integration package is currently installed.

    Each entry contains:
      provider   – provider identifier string
      human_name – display name
      description – short description of the store
    """
    return [
        {
            "provider": entry["provider"],
            "human_name": entry["human_name"],
            "description": entry["description"],
        }
        for entry in _STORE_REGISTRY
        if _is_available(entry["provider"])
    ]
