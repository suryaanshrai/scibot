from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import re
import unicodedata
from uuid import uuid4

import asyncpg

from app.config.settings import POSTGRES_ASYNC_URL

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


class ChatDatabaseUnavailable(RuntimeError):
    pass


def _raise_chat_db_unavailable(action: str, exc: Exception) -> None:
    raise ChatDatabaseUnavailable(
        f"Chat database unavailable while {action}. "
        "Ensure PostgreSQL is running and POSTGRES_ASYNC_URL is reachable."
    ) from exc


# ── Connection pool ───────────────────────────────────────────────────────────

async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            try:
                pool = await asyncpg.create_pool(
                    POSTGRES_ASYNC_URL,
                    min_size=2,
                    max_size=10,
                    command_timeout=10,
                    init=_init_connection,
                )
                _pool = pool
            except Exception as exc:
                _raise_chat_db_unavailable("connecting to PostgreSQL", exc)
    return _pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSONB codec so Python dicts are transparently serialised."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


# ── Schema bootstrap ──────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS scibot_chats (
    chat_id         TEXT        PRIMARY KEY,
    chat_slug       TEXT,
    username        TEXT        NOT NULL,
    title           TEXT,
    collection_name TEXT,
    config_override JSONB,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scibot_chats_username
    ON scibot_chats (username);

CREATE UNIQUE INDEX IF NOT EXISTS idx_scibot_chats_username_slug
    ON scibot_chats (username, chat_slug)
    WHERE chat_slug IS NOT NULL AND chat_slug <> '';

CREATE TABLE IF NOT EXISTS scibot_messages (
    message_id     TEXT        PRIMARY KEY,
    chat_id        TEXT        NOT NULL
                               REFERENCES scibot_chats(chat_id) ON DELETE CASCADE,
    role           TEXT        NOT NULL,
    content        TEXT        NOT NULL DEFAULT '',
    timestamp      TIMESTAMPTZ NOT NULL,
    task_id        TEXT,
    source_records JSONB,
    interrupted    BOOLEAN     NOT NULL DEFAULT FALSE,
    status         TEXT        NOT NULL DEFAULT 'completed'
);

CREATE INDEX IF NOT EXISTS idx_scibot_messages_chat_ts
    ON scibot_messages (chat_id, timestamp);
"""


async def init_chat_db() -> None:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(_DDL)
            await _backfill_missing_chat_slugs(conn)
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("initialising chat tables", exc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(record: asyncpg.Record | None) -> dict | None:
    return dict(record) if record else None


def _rows(records) -> list[dict]:
    return [dict(r) for r in records]


def _slugify(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "chat")
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or "chat"


async def _build_unique_chat_slug(
    conn: asyncpg.Connection,
    username: str,
    title: str | None,
    *,
    exclude_chat_id: str | None = None,
) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while True:
        if exclude_chat_id:
            existing = await conn.fetchval(
                "SELECT 1 FROM scibot_chats "
                "WHERE username=$1 AND chat_slug=$2 AND chat_id<>$3",
                username, slug, exclude_chat_id,
            )
        else:
            existing = await conn.fetchval(
                "SELECT 1 FROM scibot_chats WHERE username=$1 AND chat_slug=$2",
                username, slug,
            )
        if not existing:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


async def _backfill_missing_chat_slugs(conn: asyncpg.Connection) -> None:
    rows = await conn.fetch(
        "SELECT chat_id, username, title FROM scibot_chats "
        "WHERE chat_slug IS NULL OR chat_slug = ''"
    )
    for row in rows:
        slug = await _build_unique_chat_slug(
            conn, row["username"], row["title"],
            exclude_chat_id=row["chat_id"],
        )
        await conn.execute(
            "UPDATE scibot_chats SET chat_slug=$1 WHERE chat_id=$2",
            slug, row["chat_id"],
        )


# ── Chats CRUD ────────────────────────────────────────────────────────────────

async def create_chat(
    username: str,
    title: str | None = None,
    collection_name: str | None = None,
    config_override: dict | None = None,
) -> dict:
    try:
        pool = await _get_pool()
        now = _now()
        chat_id = uuid4().hex
        async with pool.acquire() as conn:
            chat_slug = await _build_unique_chat_slug(
                conn, username, title, exclude_chat_id=chat_id
            )
            await conn.execute(
                """
                INSERT INTO scibot_chats
                    (chat_id, chat_slug, username, title, collection_name,
                     config_override, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                chat_id, chat_slug, username, title, collection_name,
                config_override, now, now,
            )
        return {
            "chat_id": chat_id,
            "chat_slug": chat_slug,
            "username": username,
            "title": title,
            "collection_name": collection_name,
            "config_override": config_override,
            "created_at": now,
            "updated_at": now,
        }
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("creating a chat", exc)


async def get_chat(chat_id: str, username: str) -> dict | None:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM scibot_chats WHERE chat_id=$1 AND username=$2",
                chat_id, username,
            )
        return _row(row)
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("loading a chat", exc)


async def get_chat_by_slug(chat_slug: str, username: str) -> dict | None:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM scibot_chats WHERE chat_slug=$1 AND username=$2",
                chat_slug, username,
            )
        return _row(row)
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("loading a chat by slug", exc)


async def list_chats(username: str) -> list[dict]:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.*,
                       COUNT(m.message_id) AS message_count
                FROM   scibot_chats    c
                LEFT JOIN scibot_messages m USING (chat_id)
                WHERE  c.username = $1
                GROUP  BY c.chat_id
                ORDER  BY c.updated_at DESC
                """,
                username,
            )
        return _rows(rows)
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("listing chats", exc)


async def update_chat(chat_id: str, username: str, updates: dict) -> dict | None:
    try:
        pool = await _get_pool()
        updates["updated_at"] = _now()

        # Build SET clause dynamically from the provided keys
        allowed = {"title", "collection_name", "config_override", "updated_at", "chat_slug"}
        cols = {k: v for k, v in updates.items() if k in allowed}
        if not cols:
            return await get_chat(chat_id, username)

        set_clause = ", ".join(
            f"{col}=${i}" for i, col in enumerate(cols.keys(), start=1)
        )
        values = list(cols.values())
        id_idx = len(values) + 1
        un_idx = len(values) + 2

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE scibot_chats SET {set_clause} "
                f"WHERE chat_id=${id_idx} AND username=${un_idx} "
                f"RETURNING *",
                *values, chat_id, username,
            )
        return _row(row)
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("updating a chat", exc)


async def delete_chat(chat_id: str, username: str) -> bool:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # scibot_messages has ON DELETE CASCADE, so one DELETE suffices
            result = await conn.execute(
                "DELETE FROM scibot_chats WHERE chat_id=$1 AND username=$2",
                chat_id, username,
            )
        return result == "DELETE 1"
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("deleting a chat", exc)


async def clear_messages(chat_id: str) -> bool:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM scibot_messages WHERE chat_id=$1", chat_id
            )
        return True
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("clearing messages for a chat", exc)


# ── Messages CRUD ─────────────────────────────────────────────────────────────

async def append_message(
    chat_id: str,
    role: str,
    content: str,
    status: str = "completed",
    task_id: str | None = None,
    source_records: list[dict] | None = None,
    interrupted: bool = False,
) -> str:
    try:
        pool = await _get_pool()
        message_id = uuid4().hex
        now = _now()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO scibot_messages
                        (message_id, chat_id, role, content, timestamp,
                         task_id, source_records, interrupted, status)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    message_id, chat_id, role, content, now,
                    task_id, source_records, interrupted, status,
                )
                await conn.execute(
                    "UPDATE scibot_chats SET updated_at=$1 WHERE chat_id=$2",
                    now, chat_id,
                )
        return message_id
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("saving a chat message", exc)


async def update_message_content(
    message_id: str,
    content: str,
    source_records: list[dict] | None,
    status: str,
    interrupted: bool = False,
) -> None:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scibot_messages
                SET content=$1, source_records=$2, status=$3, interrupted=$4
                WHERE message_id=$5
                """,
                content, source_records, status, interrupted, message_id,
            )
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("updating a chat message", exc)


async def get_messages(
    chat_id: str,
    limit: int = 50,
    skip: int = 0,
) -> list[dict]:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM scibot_messages
                WHERE chat_id=$1
                ORDER BY timestamp ASC
                LIMIT $2 OFFSET $3
                """,
                chat_id, limit, skip,
            )
        return _rows(rows)
    except ChatDatabaseUnavailable:
        raise
    except Exception as exc:
        _raise_chat_db_unavailable("loading chat messages", exc)


