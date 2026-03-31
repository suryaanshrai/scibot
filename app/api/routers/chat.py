from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.chat_db import (
    ChatDatabaseUnavailable,
    append_message,
    clear_messages,
    create_chat,
    delete_chat,
    get_chat,
    get_messages,
    list_chats,
    update_chat,
    update_message_content,
)
from app.api.deps import AuthUser, get_current_user
from app.api.models import (
    ChatDetail,
    ChatSummary,
    CreateChatRequest,
    MessageOut,
    ResumeRequest,
    SendMessageRequest,
    UpdateChatRequest,
)
from app.config.settings import REDIS_AGENT_URL
from app.workers.agent_worker import task_resume_agent, task_run_agent

router = APIRouter()

_SSE_TIMEOUT = 300  # 5 minutes max stream time


def _raise_chat_db_http_error(exc: ChatDatabaseUnavailable) -> None:
    raise HTTPException(status_code=503, detail=str(exc)) from exc


# ── Chats CRUD ────────────────────────────────────────────────────────────────

@router.post("", status_code=201, response_model=ChatDetail)
async def create_new_chat(
    req: CreateChatRequest,
    user: AuthUser = Depends(get_current_user),
) -> ChatDetail:
    try:
        doc = await create_chat(
            user.username,
            title=req.title,
            collection_name=req.collection_name,
            config_override=req.config_override,
        )
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    return ChatDetail(**doc)


@router.get("", response_model=list[ChatSummary])
async def list_user_chats(
    user: AuthUser = Depends(get_current_user),
) -> list[ChatSummary]:
    try:
        chats = await list_chats(user.username)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    return [ChatSummary(**c) for c in chats]


@router.get("/{chat_id}", response_model=ChatDetail)
async def get_chat_detail(
    chat_id: str,
    user: AuthUser = Depends(get_current_user),
) -> ChatDetail:
    try:
        chat = await get_chat(chat_id, user.username)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return ChatDetail(**chat)


@router.patch("/{chat_id}", response_model=ChatDetail)
async def update_chat_detail(
    chat_id: str,
    req: UpdateChatRequest,
    user: AuthUser = Depends(get_current_user),
) -> ChatDetail:
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        doc = await update_chat(chat_id, user.username, updates)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    if not doc:
        raise HTTPException(status_code=404, detail="Chat not found")
    return ChatDetail(**doc)


@router.delete("/{chat_id}", status_code=204)
async def delete_chat_endpoint(
    chat_id: str,
    user: AuthUser = Depends(get_current_user),
) -> None:
    try:
        deleted = await delete_chat(chat_id, user.username)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat not found")


@router.post("/{chat_id}/clear", status_code=204)
async def clear_chat_messages(
    chat_id: str,
    user: AuthUser = Depends(get_current_user),
) -> None:
    """Delete all messages for a chat and wipe the LangGraph checkpoint state,
    so the LLM starts fresh on the next turn."""
    try:
        chat = await get_chat(chat_id, user.username)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Clear MongoDB messages
    try:
        await clear_messages(chat_id)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)

    # Wipe LangGraph Redis checkpoint state for this thread
    thread_key = f"{user.username}:{chat_id}"
    r = aioredis.from_url(REDIS_AGENT_URL, decode_responses=True)
    try:
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=f"*{thread_key}*", count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    finally:
        await r.aclose()


@router.get("/{chat_id}/messages", response_model=list[MessageOut])
async def get_chat_messages(
    chat_id: str,
    limit: int = 50,
    skip: int = 0,
    user: AuthUser = Depends(get_current_user),
) -> list[MessageOut]:
    try:
        chat = await get_chat(chat_id, user.username)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    try:
        msgs = await get_messages(chat_id, limit=limit, skip=skip)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    return [MessageOut(**m) for m in msgs]


# ── SSE Streaming ─────────────────────────────────────────────────────────────

async def _stream_agent_events(
    task_id: str,
    message_id: str,
) -> AsyncIterator[str]:
    async def _try_update_message(
        content: str,
        records: list[dict] | None,
        status: str,
        *,
        interrupted_value: bool = False,
    ) -> None:
        try:
            await update_message_content(
                message_id,
                content,
                records,
                status,
                interrupted=interrupted_value,
            )
        except ChatDatabaseUnavailable:
            return

    r = aioredis.from_url(REDIS_AGENT_URL, decode_responses=True)
    ps = r.pubsub()
    await ps.subscribe(f"agent_events:{task_id}")

    full_answer = ""
    source_records = None
    interrupted = False
    deadline = time.monotonic() + _SSE_TIMEOUT

    try:
        while time.monotonic() < deadline:
            msg = await ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                # Keep-alive comment to prevent proxy timeouts
                yield ": keepalive\n\n"
                continue

            try:
                data = json.loads(msg["data"])
            except (json.JSONDecodeError, TypeError):
                continue

            event_type = data.get("type")

            if event_type == "token":
                full_answer += data.get("content", "")
                yield f"data: {json.dumps(data)}\n\n"

            elif event_type == "tool_start":
                yield f"data: {json.dumps(data)}\n\n"

            elif event_type == "sources":
                source_records = data.get("records")
                yield f"data: {json.dumps(data)}\n\n"

            elif event_type == "interrupt":
                interrupted = True
                await _try_update_message(
                    full_answer,
                    source_records,
                    "completed",
                    interrupted_value=True,
                )
                yield f"data: {json.dumps(data)}\n\n"
                break

            elif event_type == "done":
                result = data.get("result", {})
                full_answer = result.get("answer", full_answer)
                source_records = result.get("source_records", source_records)
                await _try_update_message(full_answer, source_records, "completed")
                yield f"data: {json.dumps(data)}\n\n"
                yield "data: [DONE]\n\n"
                break

            elif event_type == "error":
                await _try_update_message(full_answer, None, "failed")
                yield f"data: {json.dumps(data)}\n\n"
                break

        else:
            # Timeout branch
            await _try_update_message(full_answer, None, "failed")
            yield f'data: {json.dumps({"type": "error", "detail": "Stream timed out"})}\n\n'

    finally:
        await ps.unsubscribe(f"agent_events:{task_id}")
        await r.aclose()


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: str,
    req: SendMessageRequest,
    user: AuthUser = Depends(get_current_user),
) -> StreamingResponse:
    try:
        chat = await get_chat(chat_id, user.username)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Merge config: chat-level override < per-request override
    effective_config = {}
    if chat.get("config_override"):
        effective_config.update(chat["config_override"])
    if req.config_override:
        effective_config.update(req.config_override)

    # Persist user message
    try:
        await append_message(chat_id, "user", req.content, "completed")
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)

    # Dispatch agent task — thread_id=chat_id preserves per-chat conversation state
    try:
        task = await asyncio.to_thread(
            task_run_agent.delay,
            user.username, user.password, req.content, chat_id, effective_config or None, chat.get("collection_name"),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent broker unavailable: {exc}")

    # Persist placeholder assistant message
    try:
        message_id = await append_message(
            chat_id, "assistant", "", "streaming", task_id=task.id
        )
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)

    return StreamingResponse(
        _stream_agent_events(task.id, message_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{chat_id}/resume")
async def resume_agent(
    chat_id: str,
    req: ResumeRequest,
    user: AuthUser = Depends(get_current_user),
) -> StreamingResponse:
    try:
        chat = await get_chat(chat_id, user.username)
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    try:
        task = await asyncio.to_thread(
            task_resume_agent.delay,
            user.username, user.password, chat_id, req.response, chat.get("collection_name"),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent broker unavailable: {exc}")

    try:
        message_id = await append_message(
            chat_id, "assistant", "", "streaming", task_id=task.id
        )
    except ChatDatabaseUnavailable as exc:
        _raise_chat_db_http_error(exc)

    return StreamingResponse(
        _stream_agent_events(task.id, message_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
