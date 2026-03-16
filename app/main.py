from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path when the file is run directly.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.chat_db import ChatDatabaseUnavailable, init_chat_db
from app.api.routers import auth, chat, collections, config, mcp
from app.users.database import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        await init_chat_db()
    except ChatDatabaseUnavailable as exc:
        logger.warning("Chat database initialization skipped: %s", exc)
    yield


# ── Inner API app ─────────────────────────────────────────────────────────────
# All routes are defined relative to this app's root (no /api prefix here).
# It is mounted at /api on the outer app below, so every route, the docs,
# openapi.json, etc. are automatically served under /api/* with no hardcoding.
api = FastAPI(
    title="SciBot API",
    version="1.0.0",
    description="AI-powered research assistant API",
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api.include_router(auth.router, prefix="/auth", tags=["auth"])
api.include_router(config.router, prefix="/config", tags=["config"])
api.include_router(collections.router, prefix="/collections", tags=["collections"])
api.include_router(chat.router, prefix="/chats", tags=["chats"])


@api.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


# ── Outer shell app ───────────────────────────────────────────────────────────
# This is what uvicorn runs. The API lives at /api and the compiled frontend is
# served at / when the build artifacts are present.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/api", api)
app.include_router(mcp.router, prefix="/mcp", tags=["mcp"])

_FRONTEND_DIST = _ROOT / "app" / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
