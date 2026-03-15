"""
Dynamic data source adapter — schema/description without vectorisation.

Dynamic data sources are registered in a collection but are NOT loaded into
the vector store.  Only lightweight schema/description metadata is stored in
the collection JSON under the ``"dynamic_data_sources"`` key.  The actual data
remains in-place (CSV/JSON files in the user's data directory, or live
Postgres/MongoDB instances) and can be queried by the agent at runtime.

Credentials for live sources (Postgres, MongoDB) are **never** stored in the
collection JSON.  Instead each source carries a ``credential_key`` that maps
to an entry in ``UserConfig.data_source_creds`` — which is Fernet-encrypted in
the users DB.

Supported source types
----------------------
  csv       — CSV file inside the user's data directory
  json      — JSON file inside the user's data directory
  postgres  — PostgreSQL table (psycopg2 required; read-only session enforced)
  mongodb   — MongoDB collection (pymongo required; read-only via find_one)

Public API
----------
load_dynamic_source(username, src, creds_map) -> dict
    Analyse the source and return a storable metadata dict.
"""

from __future__ import annotations

import csv as _csv
import json as _json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Required, TypedDict


# ── TypedDicts ────────────────────────────────────────────────────────────────

class DataSourceCredConfig(TypedDict, total=False):
    """
    Credential entry stored under ``UserConfig.data_source_creds[alias]``.

    Example (encrypted in DB, never stored in collection JSON)::

        "my_pg": {
            "type": "postgres",
            "connection_string": "postgresql://user:pass@host:5432/mydb"
        },
        "my_mongo": {
            "type": "mongodb",
            "connection_string": "mongodb://user:pass@host:27017",
            "database": "analytics"
        }
    """
    type:              Required[str]  # "postgres" | "mongodb"
    connection_string: Required[str]
    database:          str            # default database to use (optional)


class DynamicDataSourceConfig(TypedDict, total=False):
    """
    Input config for a single dynamic data source, as supplied by the caller.

    File sources (csv / json)
    -------------------------
    ``file_path`` is a path **relative to the user's data root**
    (``app/data/{username}/``).  Absolute paths and traversal sequences are
    rejected.

    Live sources (postgres / mongodb)
    ----------------------------------
    ``credential_key`` must match a key in ``UserConfig.data_source_creds``.
    Credentials are resolved at analysis time and never written to the
    collection JSON.
    """
    source_type:      Required[str]  # "csv" | "json" | "postgres" | "mongodb"

    # ── File sources ──────────────────────────────────────────────────────────
    file_path:        str            # relative to app/data/{username}/

    # ── Live sources ──────────────────────────────────────────────────────────
    credential_key:   str            # key in UserConfig.data_source_creds
    database:         str            # override the credential-default database/schema
    table:            str            # postgres: specific table to inspect
    mongo_collection: str            # mongodb: specific collection to inspect

    # ── Shared ────────────────────────────────────────────────────────────────
    description:      str            # if provided by the user, analysis is skipped


# ── Internal helpers ──────────────────────────────────────────────────────────

# app/data/
_APP_DATA_DIR = Path(__file__).parent.parent / "data"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_user_file_path(username: str, file_path: str) -> Path:
    """
    Resolve *file_path* against the user's data root and validate it stays
    within that root (path-traversal guard).

    Parameters
    ----------
    username  : owning user
    file_path : relative path supplied by the caller, e.g. ``"mydata/sales.csv"``

    Returns
    -------
    Absolute, resolved ``Path``.

    Raises
    ------
    ValueError
        If *file_path* is empty, absolute, or resolves outside the user's data
        directory.
    FileNotFoundError
        If the resolved path does not exist.
    """
    if not file_path:
        raise ValueError("file_path must not be empty.")

    if Path(file_path).is_absolute():
        raise ValueError(
            f"file_path must be a relative path, not an absolute one: {file_path!r}"
        )

    user_root = (_APP_DATA_DIR / username).resolve()
    resolved = (user_root / file_path).resolve()

    # Reject traversal attempts.
    try:
        resolved.relative_to(user_root)
    except ValueError:
        raise ValueError(
            f"file_path {file_path!r} escapes the user data directory — "
            "path traversal is not allowed."
        )

    if not resolved.exists():
        raise FileNotFoundError(f"Data file not found: {resolved}")

    if not resolved.is_file():
        raise ValueError(f"Path is not a regular file: {resolved}")

    return resolved


# ── Sparse analyzers ──────────────────────────────────────────────────────────

_MAX_CSV_ROWS = 1_000


def _analyze_csv(path: Path) -> dict:
    """
    Return a lightweight schema dict for a CSV file.

    Tries pandas for dtype inference (reads up to 1 000 rows); falls back to
    the stdlib ``csv`` module.  No more than 1 000 rows are ever read.
    """
    try:
        import pandas as pd  # type: ignore[import-untyped]

        df = pd.read_csv(path, nrows=_MAX_CSV_ROWS, low_memory=False)
        columns = [{"name": col, "type": str(df[col].dtype)} for col in df.columns]
        sample: dict[str, list] = {
            col: df[col].dropna().head(3).tolist() for col in df.columns
        }
        return {
            "columns": columns,
            "row_count_estimate": int(len(df)),
            "sample_values": sample,
            "analysis_method": "pandas",
        }
    except ImportError:
        pass  # fall back to stdlib csv

    columns_seen: list[str] = []
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = _csv.DictReader(fh)
        columns_seen = list(reader.fieldnames or [])
        for i, row in enumerate(reader):
            if i >= _MAX_CSV_ROWS:
                break
            rows.append(dict(row))

    sample_values: dict[str, list] = {
        col: [r[col] for r in rows if r.get(col)][:3] for col in columns_seen
    }
    return {
        "columns": [{"name": c, "type": "unknown"} for c in columns_seen],
        "row_count_estimate": len(rows),
        "sample_values": sample_values,
        "analysis_method": "csv",
    }


def _analyze_json(path: Path) -> dict:
    """
    Return a lightweight schema dict for a JSON file.

    Handles top-level arrays and objects.  Only the first element of an array
    is inspected for key inference.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        data = _json.load(fh)

    if isinstance(data, list):
        first = data[0] if data else {}
        keys = list(first.keys()) if isinstance(first, dict) else []
        return {
            "structure": "array",
            "item_count": len(data),
            "keys": keys,
            "analysis_method": "json",
        }

    if isinstance(data, dict):
        return {
            "structure": "object",
            "keys": list(data.keys()),
            "analysis_method": "json",
        }

    return {
        "structure": type(data).__name__,
        "analysis_method": "json",
    }


def _analyze_postgres(conn_string: str, database: str | None, table: str | None) -> dict:
    """
    Return schema info for a PostgreSQL table.

    Queries ``information_schema.columns`` for column metadata and
    ``pg_class.reltuples`` for a fast row-count estimate.  A **read-only**
    session is explicitly set before any query is executed.

    Requires ``psycopg2-binary`` or ``psycopg2``.
    """
    try:
        import psycopg2  # type: ignore[import-untyped]
        import psycopg2.extras  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "psycopg2 is required for Postgres dynamic data sources. "
            "Install it with: pip install psycopg2-binary"
        ) from exc

    connect_kwargs: dict = {"dsn": conn_string}
    if database:
        connect_kwargs["dbname"] = database

    conn = psycopg2.connect(**connect_kwargs)
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            columns: list[dict] = []
            row_count: int | None = None

            if table:
                cur.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM   information_schema.columns
                    WHERE  table_name = %s
                    ORDER  BY ordinal_position
                    """,
                    (table,),
                )
                columns = [dict(row) for row in cur.fetchall()]

                cur.execute(
                    "SELECT reltuples::bigint AS estimate FROM pg_class WHERE relname = %s",
                    (table,),
                )
                result = cur.fetchone()
                # reltuples is -1 for tables that have never been ANALYSEd.
                if result and result["estimate"] >= 0:
                    row_count = int(result["estimate"])
    finally:
        conn.close()

    return {
        "columns": columns,
        "row_count_estimate": row_count,
        "analysis_method": "postgres_information_schema",
    }


def _analyze_mongodb(
    conn_string: str, database: str | None, mongo_collection: str | None
) -> dict:
    """
    Return schema info for a MongoDB collection.

    Uses ``estimated_document_count()`` for a fast count and inspects a single
    document (``find_one``) to infer the field list.  No writes are performed.

    Requires ``pymongo``.
    """
    try:
        from pymongo import MongoClient  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "pymongo is required for MongoDB dynamic data sources. "
            "Install it with: pip install pymongo"
        ) from exc

    client: MongoClient = MongoClient(conn_string)
    try:
        db_name = database
        if not db_name:
            # Fall back to the database encoded in the URI, if any.
            default_db = client.get_default_database(default=None)
            db_name = default_db.name if default_db is not None else None
        if not db_name:
            raise ValueError(
                "No database specified and none encoded in the connection string. "
                "Provide 'database' in DynamicDataSourceConfig or in the credential entry."
            )

        db = client[db_name]

        if mongo_collection:
            coll = db[mongo_collection]
            doc_count: int | None = coll.estimated_document_count()
            sample_doc = coll.find_one({}, {"_id": 0})
            keys = list(sample_doc.keys()) if sample_doc else []
        else:
            # No specific collection: list all collection names in the database.
            keys = db.list_collection_names()
            doc_count = None
    finally:
        client.close()

    return {
        "keys": keys,
        "document_count_estimate": doc_count,
        "analysis_method": "mongodb_find_one",
    }


# ── Auto-description builder ──────────────────────────────────────────────────

def _build_description(source_type: str, schema_info: dict) -> str:
    """Construct a brief human-readable description from *schema_info*."""
    if source_type == "csv":
        cols = ", ".join(c["name"] for c in schema_info.get("columns", [])[:10])
        n = schema_info.get("row_count_estimate", "?")
        suffix = " (first 1 000 rows sampled)" if n == _MAX_CSV_ROWS else ""
        return f"CSV file with ~{n} rows{suffix}. Columns: {cols}."

    if source_type == "json":
        structure = schema_info.get("structure", "unknown")
        keys = schema_info.get("keys", [])[:10]
        if structure == "array":
            return (
                f"JSON array with {schema_info.get('item_count', '?')} items. "
                f"Keys: {', '.join(keys)}."
            )
        return f"JSON object with keys: {', '.join(keys)}."

    if source_type == "postgres":
        cols = ", ".join(
            f"{c['column_name']} ({c['data_type']})"
            for c in schema_info.get("columns", [])[:10]
        )
        n = schema_info.get("row_count_estimate")
        count_str = f"~{n}" if n is not None else "unknown (run ANALYZE)"
        return f"PostgreSQL table with {count_str} rows. Columns: {cols}."

    if source_type == "mongodb":
        keys = ", ".join(schema_info.get("keys", [])[:10])
        n = schema_info.get("document_count_estimate", "?")
        return f"MongoDB collection with ~{n} documents. Fields: {keys}."

    return f"{source_type} data source."


# ── Public API ────────────────────────────────────────────────────────────────

def load_dynamic_source(
    username: str,
    src: DynamicDataSourceConfig,
    creds_map: dict[str, DataSourceCredConfig],
) -> dict:
    """
    Analyse *src* and return a storable metadata dict for inclusion in the
    collection's ``"dynamic_data_sources"`` list.

    The caller supplies *creds_map* — the contents of
    ``UserConfig.data_source_creds`` — so that credentials are never stored in
    the collection JSON; only the ``credential_key`` alias is persisted.

    Parameters
    ----------
    username  : owning user (used to resolve and validate file paths)
    src       : source config as supplied by the caller
    creds_map : ``UserConfig.data_source_creds`` dict (may be empty)

    Returns
    -------
    A dict suitable for storing in the collection JSON.  Always contains:
      ``source_type``, ``description``, ``description_source``

    On successful analysis also contains: ``schema_info``, ``analyzed_at``
    On analysis failure also contains: ``analysis_error`` (str)

    The dict is intentionally free of any credential values.
    """
    source_type: str = src["source_type"]
    user_description: str | None = src.get("description")

    # Build the base entry with identifying fields (no credentials).
    entry: dict = {"source_type": source_type}
    for field in ("credential_key", "file_path", "database", "table", "mongo_collection"):
        val = src.get(field)  # type: ignore[literal-required]
        if val is not None:
            entry[field] = val

    # ── Skip analysis if the user supplied a description ─────────────────────
    if user_description:
        entry["description"] = user_description
        entry["description_source"] = "user"
        return entry

    # ── Validate file path BEFORE the try/except so security violations ───────
    # (path traversal) always propagate to the caller and are never silenced.
    resolved_file_path: Path | None = None
    if source_type in ("csv", "json"):
        resolved_file_path = _resolve_user_file_path(username, src.get("file_path") or "")

    # ── Run sparse analysis ───────────────────────────────────────────────────
    schema_info: dict = {}
    analysis_error: str | None = None

    try:
        if source_type == "csv":
            schema_info = _analyze_csv(resolved_file_path)  # type: ignore[arg-type]

        elif source_type == "json":
            schema_info = _analyze_json(resolved_file_path)  # type: ignore[arg-type]

        elif source_type == "postgres":
            cred_key = src.get("credential_key") or ""
            cred = creds_map.get(cred_key)
            if cred is None:
                raise KeyError(
                    f"Credential key {cred_key!r} not found in data_source_creds. "
                    "Register it via update_user_config."
                )
            conn_str = cred["connection_string"]
            database = src.get("database") or cred.get("database")
            table = src.get("table")
            schema_info = _analyze_postgres(conn_str, database, table)

        elif source_type == "mongodb":
            cred_key = src.get("credential_key") or ""
            cred = creds_map.get(cred_key)
            if cred is None:
                raise KeyError(
                    f"Credential key {cred_key!r} not found in data_source_creds. "
                    "Register it via update_user_config."
                )
            conn_str = cred["connection_string"]
            database = src.get("database") or cred.get("database")
            mongo_coll = src.get("mongo_collection")
            schema_info = _analyze_mongodb(conn_str, database, mongo_coll)

        else:
            raise ValueError(
                f"Unknown dynamic source type {source_type!r}. "
                "Must be one of: csv, json, postgres, mongodb."
            )

    except Exception as exc:
        analysis_error = f"{type(exc).__name__}: {exc}"
        print(
            f"[dynamic_data] WARNING — analysis failed for {source_type!r} source: {exc}",
            file=sys.stderr,
        )

    if analysis_error:
        entry["description"] = f"Auto-analysis failed: {analysis_error}"
        entry["description_source"] = "analyzed"
        entry["analysis_error"] = analysis_error
    else:
        entry["schema_info"] = schema_info
        entry["description"] = _build_description(source_type, schema_info)
        entry["description_source"] = "analyzed"
        entry["analyzed_at"] = _now_iso()

    return entry
