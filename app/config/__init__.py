"""
app.config — configuration management for scibot.

Public API
----------
get_llm(config=None)
    Return an initialised LangChain chat model.

get_embedding_model(config=None)
    Return an initialised LangChain embedding model.

get_store(config=None, embedding=None)
    Return an initialised LangChain vector store.

list_llms()
    List all supported LLM providers/models (installed packages only).

list_embeddings()
    List all supported embedding providers/models (installed packages only).

list_stores()
    List all supported vector store providers (installed packages only).

Each factory accepts an optional ``config`` dict. Keys common to all:
  provider    – which provider to use
  model       – model identifier
  api_key     – provider API key (overrides env)

Provider-specific keys and all defaults (via env vars) are documented
in the individual modules and in ``.env.example``.
"""

from app.config.embedding_model import get_embedding_model, list_embeddings
from app.config.llm_model import get_llm, list_llms
from app.config.store import get_store, list_stores

__all__ = [
    "get_llm",
    "get_embedding_model",
    "get_store",
    "list_llms",
    "list_embeddings",
    "list_stores",
]
