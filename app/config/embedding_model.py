"""
Embedding model configuration — registry, factory, and listing.

Usage:
    from app.config.embedding_model import get_embedding_model, list_embeddings

    # Default (from env)
    embeddings = get_embedding_model()

    # Explicit config
    embeddings = get_embedding_model({
        "provider": "cohere",
        "model": "embed-english-v3.0",
    })

    # With custom output dimensions (OpenAI / Google GenAI)
    embeddings = get_embedding_model({
        "provider": "openai",
        "model": "text-embedding-3-large",
        "dimensions": 1024,
    })
"""

from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from typing import Any

from app.config.settings import (
    COHERE_API_KEY,
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    GOOGLE_API_KEY,
    HUGGINGFACEHUB_API_TOKEN,
    IBM_API_KEY,
    IBM_PROJECT_ID,
    IBM_URL,
    MISTRAL_API_KEY,
    OLLAMA_BASE_URL,
    OPENAI_API_KEY,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Maps provider identifier → importable package (internal; not exposed to callers).
_EMBEDDING_PACKAGES: dict[str, str] = {
    "openai": "langchain_openai",
    "google_genai": "langchain_google_genai",
    "ollama": "langchain_ollama",
    "mistral": "langchain_mistralai",
    "cohere": "langchain_cohere",
    "huggingface": "langchain_huggingface",
    "ibm": "langchain_ibm",
}

_EMBEDDING_REGISTRY: list[dict[str, Any]] = [
    {
        "provider": "openai",
        "human_name": "OpenAI",
        "default_model": "text-embedding-3-small",
        "supports_dimensions": True,
        "models": [
            {"id": "text-embedding-3-small", "name": "Text Embedding 3 Small"},
            {"id": "text-embedding-3-large", "name": "Text Embedding 3 Large"},
            {"id": "text-embedding-ada-002", "name": "Text Embedding Ada 002"},
        ],
    },
    {
        "provider": "google_genai",
        "human_name": "Google Gemini",
        "default_model": "gemini-embedding-001",
        "supports_dimensions": True,
        "models": [
            {"id": "gemini-embedding-001", "name": "Gemini Embedding 001"},
            {"id": "gemini-embedding-2-preview", "name": "Gemini Embedding 2 (Preview)"},
        ],
    },
    {
        "provider": "ollama",
        "human_name": "Ollama (local)",
        "default_model": "nomic-embed-text",
        "supports_dimensions": False,
        "models": [
            {"id": "nomic-embed-text", "name": "Nomic Embed Text"},
            {"id": "mxbai-embed-large", "name": "MxBAI Embed Large"},
            {"id": "all-minilm", "name": "All MiniLM"},
            {"id": "snowflake-arctic-embed", "name": "Snowflake Arctic Embed"},
        ],
    },
    {
        "provider": "mistral",
        "human_name": "Mistral AI",
        "default_model": "mistral-embed",
        "supports_dimensions": False,
        "models": [
            {"id": "mistral-embed", "name": "Mistral Embed"},
        ],
    },
    {
        "provider": "cohere",
        "human_name": "Cohere",
        "default_model": "embed-v4.0",
        "supports_dimensions": False,
        "models": [
            {"id": "embed-v4.0", "name": "Embed v4.0"},
            {"id": "embed-english-v3.0", "name": "Embed English v3.0"},
            {"id": "embed-multilingual-v3.0", "name": "Embed Multilingual v3.0"},
            {"id": "embed-english-light-v3.0", "name": "Embed English Light v3.0"},
            {"id": "embed-multilingual-light-v3.0", "name": "Embed Multilingual Light v3.0"},
        ],
    },
    {
        "provider": "huggingface",
        "human_name": "Hugging Face",
        "default_model": "sentence-transformers/all-MiniLM-L6-v2",
        "supports_dimensions": False,
        "models": [
            {"id": "sentence-transformers/all-MiniLM-L6-v2", "name": "All MiniLM L6 v2"},
            {"id": "sentence-transformers/all-mpnet-base-v2", "name": "All MPNet Base v2"},
            {"id": "BAAI/bge-small-en-v1.5", "name": "BGE Small EN v1.5"},
            {"id": "BAAI/bge-large-en-v1.5", "name": "BGE Large EN v1.5"},
            {"id": "intfloat/multilingual-e5-large", "name": "Multilingual E5 Large"},
        ],
    },
    {
        "provider": "ibm",
        "human_name": "IBM watsonx.ai",
        "default_model": "ibm/slate-125m-english-rtrvr",
        "supports_dimensions": False,
        "models": [
            {"id": "ibm/slate-125m-english-rtrvr", "name": "Slate 125M English Retriever"},
            {"id": "ibm/slate-30m-english-rtrvr", "name": "Slate 30M English Retriever"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_available(provider: str) -> bool:
    pkg = _EMBEDDING_PACKAGES.get(provider)
    return pkg is not None and importlib.util.find_spec(pkg) is not None


def _get_registry_entry(provider: str) -> dict[str, Any]:
    for entry in _EMBEDDING_REGISTRY:
        if entry["provider"] == provider:
            return entry
    supported = [e["provider"] for e in _EMBEDDING_REGISTRY]
    raise ValueError(
        f"Unsupported embedding provider: '{provider}'. "
        f"Supported providers: {supported}"
    )


def _config_cache_key(config: dict[str, Any] | None) -> str:
    return json.dumps(config or {}, sort_keys=True, separators=(",", ":"), default=str)


@lru_cache(maxsize=32)
def _get_embedding_model_cached(config_key: str) -> Any:
    return _build_embedding_model(json.loads(config_key))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _build_embedding_model(config: dict[str, Any] | None = None) -> Any:
    """
    Return an initialised LangChain embedding model.

    Parameters
    ----------
    config : dict, optional
        Supported keys:
          provider     – one of the providers in the registry (default: env DEFAULT_EMBEDDING_PROVIDER)
          model        – model identifier string
          dimensions   – output vector dimensions (only OpenAI and Google GenAI support this)
          api_key      – override the provider API key from env
          base_url     – override base URL (Ollama)
          extra_kwargs – dict; any additional keyword arguments passed directly to the
                         provider's constructor, merged last (can override named params)
    """
    cfg = config or {}

    provider = cfg.get("provider") or DEFAULT_EMBEDDING_PROVIDER or "openai"
    entry = _get_registry_entry(provider)

    model = cfg.get("model") or DEFAULT_EMBEDDING_MODEL or entry["default_model"]

    raw_dims = cfg.get("dimensions") or DEFAULT_EMBEDDING_DIMENSIONS
    dimensions = int(raw_dims) if raw_dims is not None else None
    extra_kwargs: dict[str, Any] = cfg.get("extra_kwargs") or {}

    # ── OpenAI ────────────────────────────────────────────────────────────────
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": cfg.get("api_key") or OPENAI_API_KEY,
        }
        if dimensions is not None:
            kwargs["dimensions"] = dimensions
        kwargs.update(extra_kwargs)
        return OpenAIEmbeddings(**kwargs)

    # ── Google Gemini ─────────────────────────────────────────────────────────
    if provider == "google_genai":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        kwargs = {
            "model": model,
            "google_api_key": cfg.get("api_key") or GOOGLE_API_KEY,
        }
        if dimensions is not None:
            kwargs["output_dimensionality"] = dimensions
        kwargs.update(extra_kwargs)
        return GoogleGenerativeAIEmbeddings(**kwargs)

    # ── Ollama ────────────────────────────────────────────────────────────────
    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=model,
            base_url=cfg.get("base_url") or OLLAMA_BASE_URL,
            **extra_kwargs,
        )

    # ── Mistral ───────────────────────────────────────────────────────────────
    if provider == "mistral":
        from langchain_mistralai import MistralAIEmbeddings

        return MistralAIEmbeddings(
            model=model,
            mistral_api_key=cfg.get("api_key") or MISTRAL_API_KEY,
            **extra_kwargs,
        )

    # ── Cohere ────────────────────────────────────────────────────────────────
    if provider == "cohere":
        from langchain_cohere import CohereEmbeddings

        return CohereEmbeddings(
            model=model,
            cohere_api_key=cfg.get("api_key") or COHERE_API_KEY,
            **extra_kwargs,
        )

    # ── Hugging Face ──────────────────────────────────────────────────────────
    if provider == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name=model,
            **extra_kwargs,
        )

    # ── IBM watsonx.ai ────────────────────────────────────────────────────────
    if provider == "ibm":
        from langchain_ibm import WatsonxEmbeddings

        return WatsonxEmbeddings(
            model_id=model,
            url=cfg.get("ibm_url") or IBM_URL,
            project_id=cfg.get("ibm_project_id") or IBM_PROJECT_ID,
            apikey=cfg.get("api_key") or IBM_API_KEY,
            **extra_kwargs,
        )

    # Should never reach here — _get_registry_entry raises first
    raise ValueError(f"Unsupported embedding provider: '{provider}'")


def get_embedding_model(config: dict[str, Any] | None = None) -> Any:
    return _get_embedding_model_cached(_config_cache_key(config))


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_embeddings() -> list[dict[str, Any]]:
    """
    Return all embedding providers whose integration package is currently installed.

    Each entry contains:
      provider          – provider identifier string
      human_name        – display name
      default_model     – default model ID
      supports_dimensions – whether custom output dimensions are supported
      models            – list of {id, name} dicts
    """
    return [
        {
            "provider": entry["provider"],
            "human_name": entry["human_name"],
            "default_model": entry["default_model"],
            "supports_dimensions": entry["supports_dimensions"],
            "models": entry["models"],
        }
        for entry in _EMBEDDING_REGISTRY
        if _is_available(entry["provider"])
    ]
