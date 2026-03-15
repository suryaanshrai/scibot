"""
SQLite database setup for SciBot user and collection data.

DB location : app/data/scibot.db

Schema
------
users
    username         TEXT  PRIMARY KEY
    password_hash    TEXT  NOT NULL        -- PBKDF2-SHA256 hex digest
    auth_salt        TEXT  NOT NULL        -- base64-encoded 16-byte salt for password hashing
    enc_salt         TEXT  NOT NULL        -- base64-encoded 16-byte salt for Fernet key derivation
    config_encrypted TEXT  NOT NULL        -- Fernet-encrypted JSON config blob
    created_at       TEXT  NOT NULL

collections
    id               INTEGER  PRIMARY KEY  AUTOINCREMENT
    username         TEXT     NOT NULL REFERENCES users(username) ON DELETE CASCADE
    collection_name  TEXT     NOT NULL
    data             TEXT     NOT NULL     -- JSON blob (collection metadata dict)
    created_at       TEXT     NOT NULL
    updated_at       TEXT     NOT NULL
    UNIQUE(username, collection_name)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "data" / "scibot.db"

# Module-level flag so init_db() is run at most once per process.
_db_initialized: bool = False


def _ensure_data_dir() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _open_raw() -> sqlite3.Connection:
    """Open a connection with WAL mode and foreign-key enforcement (no schema init)."""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they do not already exist.  Safe to call multiple times."""
    global _db_initialized
    _ensure_data_dir()
    conn = _open_raw()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                username         TEXT NOT NULL PRIMARY KEY,
                password_hash    TEXT NOT NULL,
                auth_salt        TEXT NOT NULL,
                enc_salt         TEXT NOT NULL,
                config_encrypted TEXT NOT NULL DEFAULT '{}',
                created_at       TEXT NOT NULL
                                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS collections (
                id              INTEGER  PRIMARY KEY AUTOINCREMENT,
                username        TEXT     NOT NULL
                                         REFERENCES users(username) ON DELETE CASCADE,
                collection_name TEXT     NOT NULL,
                data            TEXT     NOT NULL DEFAULT '{}',
                created_at      TEXT     NOT NULL
                                         DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at      TEXT     NOT NULL
                                         DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                UNIQUE (username, collection_name)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    _db_initialized = True


@contextmanager
def get_connection():
    """
    Context manager that yields an open ``sqlite3.Connection``.

    Lazily initialises the DB schema on the first call.
    Commits on clean exit; rolls back on any exception.
    """
    global _db_initialized
    if not _db_initialized:
        init_db()

    _ensure_data_dir()
    conn = _open_raw()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
