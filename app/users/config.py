"""
Per-user configuration management.

Each user's configuration is stored as a single Fernet-encrypted JSON blob in
the ``users.config_encrypted`` column.  Encrypting the entire payload — rather
than individual fields — means no configuration key names or values are visible
in the database without the user's password.

UserConfig structure (all keys optional)
-----------------------------------------
{
    "llm": {
        "provider":    "openai",          # provider name understood by get_llm()
        "model":       "gpt-4o-mini",     # model identifier
        "temperature": 0.7,
        "max_tokens":  null,
        "api_key":     "sk-..."           # overrides the env-var when present
    },
    "embedding": {
        "provider": "openai",
        "model":    "text-embedding-3-small",
        "api_key":  "sk-..."
    },
    "store": {
        "provider":         "chroma",
        "collection_name":  "scibot",
        # ... any connection-specific keys (qdrant_url, pinecone_api_key, …)
    },
    "external_keys": {
        "SEMANTIC_SCHOLAR_API_KEY": "...",
        "NCBI_API_KEY":            "...",
        "GITHUB_TOKEN":            "ghp_..."
    }
}

Public API
----------
get_user_config(username, password)                -> UserConfig
set_user_config(username, password, config)        -> None
update_user_config(username, password, updates)    -> UserConfig
resolve_config(username, password, override)       -> dict
"""

from __future__ import annotations

from typing import TypedDict

from app.users.crypto import decrypt_json, encrypt_json
from app.users.database import get_connection
from app.users.users import authenticate


class UserConfig(TypedDict, total=False):
    llm: dict
    embedding: dict
    store: dict
    external_keys: dict


# ── Helpers ───────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict that is *base* deep-merged with *override*."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def get_user_config(username: str, password: str) -> UserConfig:
    """
    Authenticate and decrypt the user's configuration.

    Raises
    ------
    AuthError   If credentials are invalid.
    ValueError  If the user does not exist.
    """
    key = authenticate(username, password)  # raises AuthError on failure
    with get_connection() as conn:
        row = conn.execute(
            "SELECT config_encrypted FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        raise ValueError(f"User {username!r} not found.")
    return decrypt_json(row["config_encrypted"], key)  # type: ignore[return-value]


def set_user_config(username: str, password: str, config: UserConfig) -> None:
    """
    Authenticate and replace the user's configuration with *config*.

    Raises
    ------
    AuthError   If credentials are invalid.
    """
    key = authenticate(username, password)
    token = encrypt_json(dict(config), key)
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET config_encrypted = ? WHERE username = ?",
            (token, username),
        )


def update_user_config(username: str, password: str, updates: dict) -> UserConfig:
    """
    Deep-merge *updates* into the existing configuration and persist.

    Returns the merged configuration.

    Raises
    ------
    AuthError   If credentials are invalid.
    """
    current = get_user_config(username, password)
    merged: UserConfig = _deep_merge(dict(current), updates)  # type: ignore[assignment]
    set_user_config(username, password, merged)
    return merged


def resolve_config(
    username: str | None,
    password: str | None,
    override: dict | None,
) -> dict:
    """
    Build an effective configuration dict by merging three layers:

        env defaults  <  per-user config (DB)  <  override dict

    The result is suitable for passing directly to ``get_llm()``,
    ``get_embedding_model()``, or ``get_store()``.

    Parameters
    ----------
    username  : if provided (together with *password*) the per-user config
                from the DB is loaded and merged.
    password  : required to decrypt the per-user config.
    override  : caller-supplied overrides; these always win.

    Notes
    -----
    Auth failures when loading the per-user config are silently swallowed —
    the function falls back to env defaults.  Callers that need to surface
    auth errors should call ``authenticate()`` explicitly.
    """
    from app.config.settings import (
        DEFAULT_EMBEDDING_MODEL,
        DEFAULT_EMBEDDING_PROVIDER,
        DEFAULT_LLM_MAX_TOKENS,
        DEFAULT_LLM_MODEL,
        DEFAULT_LLM_PROVIDER,
        DEFAULT_LLM_TEMPERATURE,
        DEFAULT_STORE_COLLECTION,
        DEFAULT_STORE_PROVIDER,
        GITHUB_TOKEN,
        NCBI_API_KEY,
        SEMANTIC_SCHOLAR_API_KEY,
    )

    # ── Layer 1: environment defaults ─────────────────────────────────────────
    env_defaults: dict = {}

    if DEFAULT_LLM_PROVIDER:
        llm_def: dict = {"provider": DEFAULT_LLM_PROVIDER}
        if DEFAULT_LLM_MODEL:
            llm_def["model"] = DEFAULT_LLM_MODEL
        if DEFAULT_LLM_TEMPERATURE:
            try:
                llm_def["temperature"] = float(DEFAULT_LLM_TEMPERATURE)
            except ValueError:
                pass
        if DEFAULT_LLM_MAX_TOKENS:
            try:
                llm_def["max_tokens"] = int(DEFAULT_LLM_MAX_TOKENS)
            except ValueError:
                pass
        env_defaults["llm"] = llm_def

    if DEFAULT_EMBEDDING_PROVIDER:
        emb_def: dict = {"provider": DEFAULT_EMBEDDING_PROVIDER}
        if DEFAULT_EMBEDDING_MODEL:
            emb_def["model"] = DEFAULT_EMBEDDING_MODEL
        env_defaults["embedding"] = emb_def

    if DEFAULT_STORE_PROVIDER:
        store_def: dict = {"provider": DEFAULT_STORE_PROVIDER}
        if DEFAULT_STORE_COLLECTION:
            store_def["collection_name"] = DEFAULT_STORE_COLLECTION
        env_defaults["store"] = store_def

    ext_def: dict = {}
    if SEMANTIC_SCHOLAR_API_KEY:
        ext_def["SEMANTIC_SCHOLAR_API_KEY"] = SEMANTIC_SCHOLAR_API_KEY
    if NCBI_API_KEY:
        ext_def["NCBI_API_KEY"] = NCBI_API_KEY
    if GITHUB_TOKEN:
        ext_def["GITHUB_TOKEN"] = GITHUB_TOKEN
    if ext_def:
        env_defaults["external_keys"] = ext_def

    # ── Layer 2: per-user config from the DB ──────────────────────────────────
    user_cfg: dict = {}
    if username and password:
        try:
            user_cfg = dict(get_user_config(username, password))
        except Exception:
            pass  # fall back to env defaults if auth fails

    # ── Layer 3: caller override ──────────────────────────────────────────────
    merged = _deep_merge(env_defaults, user_cfg)
    if override:
        merged = _deep_merge(merged, override)
    return merged
