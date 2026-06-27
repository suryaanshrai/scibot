"""
Collection data layer — SQLite CRUD for per-user collection metadata.

All collection content is stored as a single JSON blob in the ``data``
column.  The actual Documents are pickled to disk and are NOT stored in
the DB; the DB holds only source metadata / structural information.

Public API
----------
save_collection(username, collection_name, data)           -> None
load_collection(username, collection_name)                 -> dict | None
list_collections(username)                                 -> list[dict]
update_collection_data(username, collection_name, data)    -> None
delete_collection_record(username, collection_name)        -> None
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.users.database import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_collection(username: str, collection_name: str, data: dict) -> None:
    """
    Persist a new collection record.

    Raises
    ------
    ValueError
        If a collection with that name already exists for this user.
    """
    now = _now_iso()
    with get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO collections (username, collection_name, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, collection_name, json.dumps(data, ensure_ascii=False), now, now),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(
                    f"Collection {collection_name!r} already exists for user {username!r}."
                ) from exc
            raise


def load_collection(username: str, collection_name: str) -> dict | None:
    """Return the collection data dict, or ``None`` if the collection is not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data FROM collections WHERE username = ? AND collection_name = ?",
            (username, collection_name),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


def list_collections(username: str) -> list[dict]:
    """
    Return summary info for all collections belonging to *username*.

    Each entry contains:
      ``collection_name``  str
      ``created_at``       ISO-8601 UTC timestamp string
      ``updated_at``       ISO-8601 UTC timestamp string
      ``source_counts``    dict mapping source category → item count
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT collection_name, data, created_at, updated_at
            FROM   collections
            WHERE  username = ?
            ORDER  BY created_at
            """,
            (username,),
        ).fetchall()

    result: list[dict] = []
    for row in rows:
        data = json.loads(row["data"])
        papers = data.get("papers") or []
        reference_count = sum(len(p.get("references") or []) for p in papers)
        source_counts = {
            "papers":      len(papers),
            "references":  reference_count,
            "youtube":     len(data.get("youtube", [])),
            "github_repos": len(data.get("github_repos", [])),
            "webpages":    len(data.get("webpages", [])),
            "videos":      len(data.get("videos", [])),
            "audios":      len(data.get("audios", [])),
            "images":      len(data.get("images", [])),
        }
        result.append(
            {
                "collection_name": row["collection_name"],
                "created_at":      row["created_at"],
                "updated_at":      row["updated_at"],
                "source_counts":   source_counts,
            }
        )
    return result


def update_collection_data(username: str, collection_name: str, data: dict) -> None:
    """Overwrite the ``data`` blob and bump ``updated_at``."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE collections
            SET    data       = ?,
                   updated_at = ?
            WHERE  username        = ?
              AND  collection_name = ?
            """,
            (json.dumps(data, ensure_ascii=False), _now_iso(), username, collection_name),
        )


def delete_collection_record(username: str, collection_name: str) -> None:
    """Remove the collection row from the database."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM collections WHERE username = ? AND collection_name = ?",
            (username, collection_name),
        )
