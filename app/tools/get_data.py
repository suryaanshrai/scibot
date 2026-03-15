"""
Data loading tool for scibot.

Reads data from a supported source and loads it into a pandas DataFrame.
The DataFrame is stored in an in-process registry under a UUID handle so that
subsequent tools (e.g. analyze_data) can reference it without re-loading.

Supported source types
----------------------
csv      : local CSV file  (file_path required)
json     : local JSON file (file_path required)
mongodb  : MongoDB collection via an alias stored in the user's encrypted config
postgres : PostgreSQL table/query via an alias stored in the user's encrypted config

Security
--------
- For csv/json: ``file_path`` is validated to be inside ``app/data/`` to prevent
  directory traversal attacks.
- For mongodb/postgres: the raw connection string is NEVER accepted as a tool
  input.  Only an alias name is accepted; the actual connection string is
  resolved from the user's encrypted ``data_source_creds`` in the database.

Returns
-------
A summary string:
    data_handle | shape | columns | dtypes | head(5)

The ``data_handle`` can be passed to ``analyze_data`` for EDA.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# ── In-process DataFrame registry ─────────────────────────────────────────────
# key: UUID string handle  →  value: pd.DataFrame
# Lifetime: current Python process (single-worker async server).
_DATA_REGISTRY: dict[str, pd.DataFrame] = {}

_APP_DATA_DIR = Path(__file__).parent.parent / "data"
_DEFAULT_LIMIT = 10_000


# ── Input schema ──────────────────────────────────────────────────────────────

class GetDataInput(BaseModel):
    source_type: Literal["csv", "json", "mongodb", "postgres"] = Field(
        description="Type of data source to load from."
    )
    file_path: str | None = Field(
        default=None,
        description="Absolute or relative path to a CSV/JSON file (required for csv/json).",
    )
    alias: str | None = Field(
        default=None,
        description=(
            "Name of a data source alias configured in the user's encrypted config "
            "(required for mongodb/postgres)."
        ),
    )
    sql_query: str | None = Field(
        default=None,
        description="SQL query to run against a Postgres source (optional; alias must be set).",
    )
    mongo_filter: dict | None = Field(
        default=None,
        description="MongoDB filter document (optional; alias must be set).",
    )
    limit: int | None = Field(
        default=None,
        description=f"Maximum number of rows to load (default {_DEFAULT_LIMIT}).",
    )
    username: str | None = Field(
        default=None,
        description="scibot username — required for mongodb/postgres to decrypt config.",
    )
    password: str | None = Field(
        default=None,
        description="scibot password — required for mongodb/postgres to decrypt config.",
    )


# ── Security helpers ──────────────────────────────────────────────────────────

def _safe_file_path(raw: str) -> Path:
    """
    Resolve *raw* to an absolute path and ensure it lives under app/data/.
    Raises ValueError on directory traversal attempts.
    """
    # Allow paths relative to the repo root as well as absolute paths
    p = Path(raw)
    if not p.is_absolute():
        p = (_APP_DATA_DIR.parent.parent / raw).resolve()
    else:
        p = p.resolve()

    # Re-resolve app data dir for comparison
    allowed = _APP_DATA_DIR.resolve()
    try:
        p.relative_to(allowed)
    except ValueError:
        raise ValueError(
            f"Access denied: {raw!r} is outside the allowed data directory."
        )
    return p


# ── Loader helpers ────────────────────────────────────────────────────────────

def _load_csv(file_path: str, limit: int) -> pd.DataFrame:
    p = _safe_file_path(file_path)
    return pd.read_csv(p, nrows=limit)


def _load_json(file_path: str, limit: int) -> pd.DataFrame:
    p = _safe_file_path(file_path)
    df = pd.read_json(p)
    return df.head(limit)


def _resolve_alias_creds(alias: str, username: str, password: str) -> dict:
    """Look up ``data_source_creds[alias]`` from the user's encrypted config."""
    from app.users.config import get_user_config
    cfg = get_user_config(username, password)
    creds: dict = cfg.get("data_source_creds") or {}
    if alias not in creds:
        raise ValueError(
            f"Data source alias {alias!r} not found in your config. "
            "Available aliases: " + (", ".join(creds.keys()) or "(none)")
        )
    return creds[alias]


def _load_mongodb(alias: str, mongo_filter: dict | None, limit: int, username: str, password: str) -> pd.DataFrame:
    import pymongo

    creds = _resolve_alias_creds(alias, username, password)
    conn_str   = creds.get("connection_string") or creds.get("uri") or ""
    db_name    = creds.get("database") or creds.get("db") or ""
    coll_name  = creds.get("collection") or alias

    if not conn_str:
        raise ValueError(f"Alias {alias!r} is missing 'connection_string' / 'uri'.")

    client = pymongo.MongoClient(conn_str, serverSelectionTimeoutMS=10_000)
    db     = client[db_name] if db_name else client.get_default_database()
    coll   = db[coll_name]
    cursor = coll.find(mongo_filter or {}, limit=limit)
    records = list(cursor)
    client.close()

    if not records:
        return pd.DataFrame()

    # Drop MongoDB internal _id (not serialisable)
    for r in records:
        r.pop("_id", None)
    return pd.DataFrame(records)


def _load_postgres(alias: str, sql_query: str | None, limit: int, username: str, password: str) -> pd.DataFrame:
    from sqlalchemy import create_engine, text

    creds      = _resolve_alias_creds(alias, username, password)
    conn_str   = creds.get("connection_string") or creds.get("url") or ""
    table_name = creds.get("table") or alias

    if not conn_str:
        raise ValueError(f"Alias {alias!r} is missing 'connection_string' / 'url'.")

    engine = create_engine(conn_str)
    query  = sql_query or f'SELECT * FROM "{table_name}" LIMIT {limit}'

    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    engine.dispose()
    return df.head(limit)


# ── Formatting helper ─────────────────────────────────────────────────────────

def _summarise(handle: str, df: pd.DataFrame) -> str:
    rows, cols = df.shape
    col_names  = ", ".join(df.columns.tolist())
    dtype_str  = "; ".join(f"{c}: {t}" for c, t in df.dtypes.items())
    try:
        head_str = df.head(5).to_string(index=False)
    except Exception:
        head_str = "(preview unavailable)"

    return (
        f"data_handle : {handle}\n"
        f"shape       : {rows} rows × {cols} columns\n"
        f"columns     : {col_names}\n"
        f"dtypes      : {dtype_str}\n\n"
        f"── Preview (first 5 rows) ──\n{head_str}"
    )


# ── Tool ─────────────────────────────────────────────────────────────────────

@tool("get_data", args_schema=GetDataInput)
def get_data(
    source_type: str,
    file_path: str | None = None,
    alias: str | None = None,
    sql_query: str | None = None,
    mongo_filter: dict | None = None,
    limit: int | None = None,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """
    Load data from a CSV file, JSON file, MongoDB collection, or PostgreSQL
    table into a pandas DataFrame and register it under a unique handle.

    The returned ``data_handle`` can be passed to ``analyze_data`` for
    exploratory analysis.

    For csv/json supply ``file_path``.
    For mongodb/postgres supply the ``alias`` name configured in your account
    (connection credentials are never passed directly to this tool).
    """
    effective_limit = min(limit or _DEFAULT_LIMIT, _DEFAULT_LIMIT)

    try:
        if source_type == "csv":
            if not file_path:
                return "Error: file_path is required for source_type='csv'."
            df = _load_csv(file_path, effective_limit)

        elif source_type == "json":
            if not file_path:
                return "Error: file_path is required for source_type='json'."
            df = _load_json(file_path, effective_limit)

        elif source_type == "mongodb":
            if not alias:
                return "Error: alias is required for source_type='mongodb'."
            if not (username and password):
                return "Error: username and password are required for mongodb sources."
            df = _load_mongodb(alias, mongo_filter, effective_limit, username, password)

        elif source_type == "postgres":
            if not alias:
                return "Error: alias is required for source_type='postgres'."
            if not (username and password):
                return "Error: username and password are required for postgres sources."
            df = _load_postgres(alias, sql_query, effective_limit, username, password)

        else:
            return f"Error: unsupported source_type {source_type!r}. Choose from: csv, json, mongodb, postgres."

    except Exception as exc:
        return f"Failed to load data: {exc}"

    if df.empty:
        return "Data loaded successfully but the result is empty (0 rows)."

    handle = str(uuid.uuid4())
    _DATA_REGISTRY[handle] = df
    return _summarise(handle, df)
