from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.chat_db import get_chat_by_slug, get_messages, list_chats
from app.tools import build_tools
from app.users.collections_db import list_collections as list_user_collections
from app.users.collections_db import load_collection

router = APIRouter()

_MCP_TOOL_USER = "__mcp__"
_MCP_TOOL_PASSWORD = "__mcp__"
_MCP_MESSAGE_LIMIT = 100
_EXPOSED_TOOL_NAMES = {
    "web_search",
    "arxiv_search",
    "pubmed_search",
    "search_storage",
}


def _capabilities() -> dict[str, Any]:
    return {
        "tools": {
            "list": True,
            "call": False,
        },
        "resources": {
            "list": True,
            "read": True,
        },
        "prompts": {
            "list": False,
            "get": False,
        },
    }


def _tool_schema(tool: Any) -> dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema and hasattr(args_schema, "model_json_schema"):
        schema = args_schema.model_json_schema()
    else:
        schema = {"type": "object", "properties": {}, "additionalProperties": False}

    properties = dict(schema.get("properties") or {})
    required = [item for item in schema.get("required", []) if item not in {"username", "password"}]
    properties.pop("username", None)
    properties.pop("password", None)

    schema["properties"] = properties
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)
    schema.pop("title", None)
    return schema


def _tool_descriptors() -> list[dict[str, Any]]:
    tools = build_tools(_MCP_TOOL_USER, _MCP_TOOL_PASSWORD)
    descriptors = []
    for tool in tools:
        if tool.name not in _EXPOSED_TOOL_NAMES:
            continue
        descriptors.append(
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": _tool_schema(tool),
                "annotations": {
                    "readOnlyHint": tool.name != "search_storage",
                    "openWorldHint": tool.name in {"web_search", "arxiv_search", "pubmed_search"},
                },
            }
        )
    return descriptors


def _resource(uri: str, name: str, description: str, contents: Any) -> dict[str, Any]:
    return {
        "uri": uri,
        "name": name,
        "description": description,
        "mimeType": "application/json",
        "contents": contents,
    }


async def _user_resources(username: str) -> list[dict[str, Any]]:
    chats, collections = await asyncio.gather(
        list_chats(username),
        asyncio.to_thread(list_user_collections, username),
    )
    return [
        _resource(
            f"scibot://users/{username}/chats",
            "User chats",
            "Chats available for this user, including stable chat slugs for MCP chat routes.",
            chats,
        ),
        _resource(
            f"scibot://users/{username}/collections",
            "User collections",
            "Collection summaries available to this user.",
            collections,
        ),
    ]


async def _chat_resources(username: str, chat_name: str) -> list[dict[str, Any]]:
    chat = await get_chat_by_slug(chat_name, username)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = await get_messages(chat["chat_id"], limit=_MCP_MESSAGE_LIMIT)
    resources = [
        _resource(
            f"scibot://users/{username}/chats/{chat_name}/metadata",
            "Chat metadata",
            "Resolved chat metadata for this MCP scope.",
            chat,
        ),
        _resource(
            f"scibot://users/{username}/chats/{chat_name}/messages",
            "Recent chat messages",
            f"Most recent {len(messages)} messages from this chat context.",
            messages,
        ),
    ]

    collection_name = chat.get("collection_name")
    if collection_name:
        collection = await asyncio.to_thread(load_collection, username, collection_name)
        if collection is not None:
            resources.append(
                _resource(
                    f"scibot://users/{username}/collections/{collection_name}",
                    "Bound collection",
                    "Collection metadata associated with this chat.",
                    collection,
                )
            )

    return resources


@router.get("/{username}")
async def get_user_mcp(username: str) -> dict[str, Any]:
    return {
        "mcp": {
            "name": "SciBot MCP",
            "version": "0.1.0",
            "mode": "metadata-only",
            "openEndpoint": True,
        },
        "scope": {
            "type": "user",
            "username": username,
        },
        "capabilities": _capabilities(),
        "tools": _tool_descriptors(),
        "resources": await _user_resources(username),
    }


@router.get("/{username}/{chat_name}")
async def get_chat_mcp(username: str, chat_name: str) -> dict[str, Any]:
    return {
        "mcp": {
            "name": "SciBot MCP",
            "version": "0.1.0",
            "mode": "metadata-only",
            "openEndpoint": True,
        },
        "scope": {
            "type": "chat",
            "username": username,
            "chatName": chat_name,
        },
        "capabilities": _capabilities(),
        "tools": _tool_descriptors(),
        "resources": await _chat_resources(username, chat_name),
    }