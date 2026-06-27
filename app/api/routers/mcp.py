from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastmcp import FastMCP

from app.api.chat_db import ChatDatabaseUnavailable, get_chat_by_slug, get_messages, list_chats
from app.tools.arxiv_search import arxiv_search as _arxiv_search_tool
from app.tools.pubmed_search import pubmed_search as _pubmed_search_tool
from app.tools.search_storage import search_storage as _search_storage_tool
from app.tools.web_search import web_search as _web_search_tool
from app.users.collections_db import list_collections as list_user_collections
from app.users.collections_db import load_collection

logger = logging.getLogger(__name__)

_MCP_TOOL_USER = "__mcp__"
_MCP_TOOL_PASSWORD = "__mcp__"
_MCP_MESSAGE_LIMIT = 100

# ── Cache of FastMCP ASGI apps keyed by (username, chat_name) ─────────────────
_mcp_apps: dict[tuple[str, str | None], Any] = {}


def _build_mcp_app(username: str, chat_name: str | None = None) -> FastMCP:
    """Build a FastMCP server scoped to a user (and optionally a chat)."""

    mcp = FastMCP(
        "SciBot MCP",
        instructions=(
            "SciBot is an AI-powered research assistant. Use its tools to search "
            "the web, academic papers on arXiv and PubMed, and user-ingested "
            "document collections."
        ),
    )

    # ── Tools ─────────────────────────────────────────────────────────────────

    @mcp.tool
    def web_search(
        query: str,
        max_results: int = 5,
        extra_domains: list[str] | None = None,
    ) -> str:
        """Search the web for information. Returns results from trusted academic
        and reference domains. Automatically selects the best available search
        backend (Tavily > SerpAPI > DuckDuckGo)."""
        return _web_search_tool.invoke({
            "query": query,
            "max_results": max_results,
            "extra_domains": extra_domains or [],
            "username": _MCP_TOOL_USER,
            "password": _MCP_TOOL_PASSWORD,
        })

    @mcp.tool
    def arxiv_search(
        query: str,
        max_results: int = 5,
        fetch_full: bool = False,
        top_n_refs: int = 0,
        depth: int = 0,
    ) -> str:
        """Search arXiv for academic papers. Returns title, authors, year, and
        abstract for each result. Set fetch_full=True to download and parse the
        full PDF of the top result."""
        return _arxiv_search_tool.invoke({
            "query": query,
            "max_results": max_results,
            "fetch_full": fetch_full,
            "top_n_refs": top_n_refs,
            "depth": depth,
        })

    @mcp.tool
    def pubmed_search(
        query: str,
        max_results: int = 5,
        fetch_full: bool = False,
        top_n_refs: int = 0,
        depth: int = 0,
    ) -> str:
        """Search PubMed for biomedical literature. Returns title, authors, year,
        and abstract. Set fetch_full=True to retrieve the full PMC text of the
        top result."""
        return _pubmed_search_tool.invoke({
            "query": query,
            "max_results": max_results,
            "fetch_full": fetch_full,
            "top_n_refs": top_n_refs,
            "depth": depth,
        })

    @mcp.tool
    async def search_storage(
        query: str,
        collection_name: str,
        k: int = 5,
        score_threshold: float = 0.3,
        source_id: str | None = None,
        source_type: str | None = None,
        filter: dict | None = None,
    ) -> str:
        """Search a SciBot document collection using semantic + MMR retrieval
        with LLM re-ranking. Returns the top-k most relevant chunks with source
        metadata and content previews."""
        return await _search_storage_tool.ainvoke({
            "query": query,
            "username": _MCP_TOOL_USER,
            "password": _MCP_TOOL_PASSWORD,
            "collection_name": collection_name,
            "k": k,
            "score_threshold": score_threshold,
            "source_id": source_id,
            "source_type": source_type,
            "filter": filter,
        })


    @mcp.tool
    async def list_collections() -> str:
        """List all document collections belonging to the current user.
        Returns collection names, creation dates, and source counts."""
        collections = await asyncio.to_thread(list_user_collections, username)
        if not collections:
            return json.dumps({"message": "No collections found.", "collections": []})
        return json.dumps({"count": len(collections), "collections": collections}, default=str)

    @mcp.tool
    async def get_collection_sources(collection_name: str) -> str:
        """Get detailed source information for a specific collection.
        Returns all ingested sources (papers, YouTube videos, webpages, etc.)
        with their titles, authors, URLs, and metadata."""
        data = await asyncio.to_thread(load_collection, username, collection_name)
        if data is None:
            return json.dumps({"error": f"Collection '{collection_name}' not found."})

        _SOURCE_KEYS = (
            "papers", "youtube", "github_repos", "webpages",
            "videos", "audios", "images", "dynamic_data_sources",
        )
        # Strip internal fields (doc_paths, ingestion ids) for a clean response
        _STRIP = {"doc_paths", "ingestion_task_id", "store_settings", "vector_collection"}
        sources: dict[str, list[dict]] = {}
        for key in _SOURCE_KEYS:
            items = data.get(key, [])
            if items:
                sources[key] = [
                    {k: v for k, v in item.items() if k not in _STRIP}
                    for item in items
                ]

        return json.dumps({
            "collection_name": collection_name,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "source_counts": {k: len(v) for k, v in sources.items()},
            "sources": sources,
        }, default=str)

    # ── Resources ─────────────────────────────────────────────────────────────

    @mcp.resource(
        f"scibot://users/{username}/chats",
        name="User chats",
        description="Chats available for this user, including stable chat slugs.",
        mime_type="application/json",
    )
    async def get_user_chats() -> str:
        try:
            chats = await list_chats(username)
        except ChatDatabaseUnavailable:
            return json.dumps([])
        return json.dumps(chats, default=str)

    @mcp.resource(
        f"scibot://users/{username}/collections",
        name="User collections",
        description="Collection summaries available to this user.",
        mime_type="application/json",
    )
    async def get_user_collections() -> str:
        collections = await asyncio.to_thread(list_user_collections, username)
        return json.dumps(collections, default=str)

    if chat_name:
        @mcp.resource(
            f"scibot://users/{username}/chats/{chat_name}/metadata",
            name="Chat metadata",
            description="Resolved chat metadata for this MCP scope.",
            mime_type="application/json",
        )
        async def get_chat_metadata() -> str:
            try:
                chat = await get_chat_by_slug(chat_name, username)
            except ChatDatabaseUnavailable:
                return json.dumps(None)
            return json.dumps(chat, default=str)

        @mcp.resource(
            f"scibot://users/{username}/chats/{chat_name}/messages",
            name="Recent chat messages",
            description=f"Most recent messages from this chat context (limit {_MCP_MESSAGE_LIMIT}).",
            mime_type="application/json",
        )
        async def get_chat_messages() -> str:
            try:
                chat = await get_chat_by_slug(chat_name, username)
                if not chat:
                    return json.dumps([])
                messages = await get_messages(chat["chat_id"], limit=_MCP_MESSAGE_LIMIT)
            except ChatDatabaseUnavailable:
                return json.dumps([])
            return json.dumps(messages, default=str)

    return mcp


def get_mcp_app(username: str, chat_name: str | None = None) -> Any:
    """Return a cached FastMCP ASGI http_app for the given scope."""
    key = (username, chat_name)
    if key not in _mcp_apps:
        mcp = _build_mcp_app(username, chat_name)
        _mcp_apps[key] = mcp.http_app(path="/")
    return _mcp_apps[key]


class MCPDispatcher:
    """ASGI app that routes /mcp/{username}[/{chat_name}] to per-scope FastMCP apps.

    Mounted at ``/mcp`` on the outer FastAPI app.  Strips the leading
    ``/{username}`` (and optional ``/{chat_name}``) segment(s) so that
    the inner FastMCP app sees requests at ``/``.

    Each inner FastMCP app requires its ASGI lifespan to be invoked so
    that the ``StreamableHTTPSessionManager`` task-group is running.
    Because apps are created lazily (on the first request for a given
    user/chat scope), the dispatcher starts each app's lifespan in a
    background task the first time the app is needed, and tears them
    all down when the dispatcher itself receives ``lifespan.shutdown``.
    """

    def __init__(self) -> None:
        # Background tasks running inner-app lifespans
        self._lifespan_tasks: dict[tuple[str, str | None], asyncio.Task[None]] = {}
        # Fires once the inner app's lifespan.startup.complete has been sent
        self._app_ready: dict[tuple[str, str | None], asyncio.Event] = {}
        # Fires when the dispatcher wants to shut the inner app down
        self._shutdown_triggers: dict[tuple[str, str | None], asyncio.Event] = {}

    # ── Inner-app lifespan management ─────────────────────────────────────

    async def _ensure_app_started(
        self, key: tuple[str, str | None], app: Any
    ) -> None:
        """Start the inner app's ASGI lifespan (once) and wait for readiness."""
        if key in self._app_ready:
            await self._app_ready[key].wait()
            return

        ready = asyncio.Event()
        shutdown_trigger = asyncio.Event()
        self._app_ready[key] = ready
        self._shutdown_triggers[key] = shutdown_trigger

        async def _run_inner_lifespan() -> None:
            startup_complete = asyncio.Event()
            receive_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            await receive_queue.put({"type": "lifespan.startup"})

            async def _receive() -> dict[str, str]:
                return await receive_queue.get()

            async def _send(message: dict[str, str]) -> None:
                if message["type"] == "lifespan.startup.complete":
                    startup_complete.set()
                    ready.set()
                elif message["type"] == "lifespan.startup.failed":
                    logger.error("Inner MCP app startup failed for %s", key)
                    ready.set()

            lifespan_coro = app(
                {"type": "lifespan", "asgi": {"version": "3.0"}},
                _receive,
                _send,
            )
            lifespan_task = asyncio.create_task(lifespan_coro)

            await startup_complete.wait()
            # Keep alive until shutdown is requested
            await shutdown_trigger.wait()

            await receive_queue.put({"type": "lifespan.shutdown"})
            try:
                await asyncio.wait_for(lifespan_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Inner MCP app lifespan timed out for %s", key)
                lifespan_task.cancel()

        task = asyncio.create_task(_run_inner_lifespan())
        self._lifespan_tasks[key] = task
        await ready.wait()

    # ── ASGI entry-point ──────────────────────────────────────────────────

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await receive()  # startup
            await send({"type": "lifespan.startup.complete"})

            await receive()  # shutdown — tear down every inner app
            for trigger in self._shutdown_triggers.values():
                trigger.set()
            for task in self._lifespan_tasks.values():
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.TimeoutError, Exception):
                    pass
            await send({"type": "lifespan.shutdown.complete"})
            return

        path: str = scope.get("path", "/")
        parts = [p for p in path.strip("/").split("/") if p]

        if not parts:
            await _send_json_error(send, 404, "Missing username in MCP path")
            return

        username = parts[0]
        chat_name = parts[1] if len(parts) >= 2 else None

        # Determine how many path segments belong to the scope prefix
        strip_count = 2 if chat_name else 1
        remaining = "/" + "/".join(parts[strip_count:]) if len(parts) > strip_count else "/"

        mcp_app = get_mcp_app(username, chat_name)

        # Ensure this app's lifespan (session manager) is running
        key = (username, chat_name)
        await self._ensure_app_started(key, mcp_app)

        # Rewrite the path so the inner FastMCP app sees requests at its root
        inner_scope = dict(scope)
        inner_scope["path"] = remaining
        mount_prefix = scope.get("root_path", "")
        if chat_name:
            inner_scope["root_path"] = f"{mount_prefix}/{username}/{chat_name}"
        else:
            inner_scope["root_path"] = f"{mount_prefix}/{username}"

        await mcp_app(inner_scope, receive, send)


async def _send_json_error(send: Any, status: int, detail: str) -> None:
    """Send a minimal JSON error response over raw ASGI."""
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })


mcp_dispatcher = MCPDispatcher()