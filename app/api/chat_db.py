from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorClient

from app.config.settings import MONGODB_CHAT_DB_NAME, MONGODB_CHAT_URL

_client: AsyncIOMotorClient | None = None
_db = None


def _get_db():
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(MONGODB_CHAT_URL)
        _db = _client[MONGODB_CHAT_DB_NAME]
    return _db


async def init_chat_db() -> None:
    db = _get_db()
    await db.chats.create_index([("username", 1)])
    await db.chats.create_index([("chat_id", 1)], unique=True)
    await db.chats.create_index([("username", 1), ("chat_slug", 1)], unique=True, sparse=True)
    await db.messages.create_index([("chat_id", 1), ("timestamp", 1)])
    await _backfill_missing_chat_slugs()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _strip_id(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "_id"}


def _slugify(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "chat")
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or "chat"


async def _build_unique_chat_slug(
    username: str,
    title: str | None,
    *,
    exclude_chat_id: str | None = None,
) -> str:
    db = _get_db()
    base = _slugify(title)
    slug = base
    suffix = 2

    while True:
        query: dict = {"username": username, "chat_slug": slug}
        if exclude_chat_id:
            query["chat_id"] = {"$ne": exclude_chat_id}
        existing = await db.chats.find_one(query, {"_id": 1})
        if not existing:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


async def _backfill_missing_chat_slugs() -> None:
    db = _get_db()
    cursor = db.chats.find(
        {
            "$or": [
                {"chat_slug": {"$exists": False}},
                {"chat_slug": None},
                {"chat_slug": ""},
            ]
        },
        {"chat_id": 1, "username": 1, "title": 1},
    )
    async for doc in cursor:
        slug = await _build_unique_chat_slug(
            doc["username"],
            doc.get("title"),
            exclude_chat_id=doc["chat_id"],
        )
        await db.chats.update_one(
            {"chat_id": doc["chat_id"]},
            {"$set": {"chat_slug": slug}},
        )


# ── Chats CRUD ────────────────────────────────────────────────────────────────

async def create_chat(
    username: str,
    title: str | None = None,
    collection_name: str | None = None,
    config_override: dict | None = None,
) -> dict:
    db = _get_db()
    now = _now()
    chat_id = uuid4().hex
    chat_slug = await _build_unique_chat_slug(username, title, exclude_chat_id=chat_id)
    doc = {
        "chat_id": chat_id,
        "chat_slug": chat_slug,
        "username": username,
        "title": title,
        "collection_name": collection_name,
        "config_override": config_override,
        "created_at": now,
        "updated_at": now,
    }
    await db.chats.insert_one(doc)
    return _strip_id(doc)


async def get_chat(chat_id: str, username: str) -> dict | None:
    db = _get_db()
    doc = await db.chats.find_one({"chat_id": chat_id, "username": username})
    return _strip_id(doc) if doc else None


async def get_chat_by_slug(chat_slug: str, username: str) -> dict | None:
    db = _get_db()
    doc = await db.chats.find_one({"chat_slug": chat_slug, "username": username})
    return _strip_id(doc) if doc else None


async def list_chats(username: str) -> list[dict]:
    db = _get_db()
    pipeline = [
        {"$match": {"username": username}},
        {
            "$lookup": {
                "from": "messages",
                "localField": "chat_id",
                "foreignField": "chat_id",
                "as": "_msgs",
            }
        },
        {"$addFields": {"message_count": {"$size": "$_msgs"}}},
        {"$project": {"_msgs": 0, "_id": 0}},
        {"$sort": {"updated_at": -1}},
    ]
    return [doc async for doc in db.chats.aggregate(pipeline)]


async def update_chat(chat_id: str, username: str, updates: dict) -> dict | None:
    db = _get_db()
    updates["updated_at"] = _now()
    result = await db.chats.find_one_and_update(
        {"chat_id": chat_id, "username": username},
        {"$set": updates},
        return_document=True,
    )
    return _strip_id(result) if result else None


async def delete_chat(chat_id: str, username: str) -> bool:
    db = _get_db()
    result = await db.chats.delete_one({"chat_id": chat_id, "username": username})
    if result.deleted_count:
        await db.messages.delete_many({"chat_id": chat_id})
        return True
    return False


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
    db = _get_db()
    message_id = uuid4().hex
    doc = {
        "message_id": message_id,
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "timestamp": _now(),
        "task_id": task_id,
        "source_records": source_records,
        "interrupted": interrupted,
        "status": status,
    }
    await db.messages.insert_one(doc)
    await db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {"updated_at": _now()}},
    )
    return message_id


async def update_message_content(
    message_id: str,
    content: str,
    source_records: list[dict] | None,
    status: str,
    interrupted: bool = False,
) -> None:
    db = _get_db()
    await db.messages.update_one(
        {"message_id": message_id},
        {
            "$set": {
                "content": content,
                "source_records": source_records,
                "status": status,
                "interrupted": interrupted,
            }
        },
    )


async def get_messages(
    chat_id: str,
    limit: int = 50,
    skip: int = 0,
) -> list[dict]:
    db = _get_db()
    cursor = (
        db.messages.find({"chat_id": chat_id}, {"_id": 0})
        .sort("timestamp", 1)
        .skip(skip)
        .limit(limit)
    )
    return [doc async for doc in cursor]
