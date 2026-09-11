"""
app.workers.agent_worker — Celery background worker for agent execution.

The ``task_run_agent`` task wraps the async ``OrchestratorAgent.astream()``
method inside a synchronous Celery task so it can be dispatched from any
caller (API, CLI, tests) without needing an event loop in the caller.

Broker + result backend
-----------------------
Uses the shared ``redis`` container (port 6379, db 0) as the Celery broker
and result backend.  Both the ingestion and agent workers share this one
instance and are isolated by their queue names (-Q ingestion / -Q agent).

LangGraph checkpointing
-----------------------
Conversation threads persist across worker restarts using
``AsyncPostgresSaver`` from ``langgraph-checkpoint-postgres``.  The saver
writes to the shared PostgreSQL instance so any worker process can resume
any conversation thread.

Streaming via pub/sub
---------------------
While a task runs it continuously publishes events to the PostgreSQL
LISTEN/NOTIFY channel ``agent_events_{task_id}`` so the API layer can
forward them in real time to SSE clients:

    {"type": "token",      "content": "<text chunk>"}
    {"type": "tool_start", "tool": "<tool name>"}
    {"type": "sources",    "count": N, "filtered": M}
    {"type": "interrupt",  "payload": {...}}        # HITL gate
    {"type": "done",       "result": {...}}         # final summary

The ``{"type": "done"}`` event is the last message; the channel is then
released.  Subscribers should close their listener after receiving it.

Start the worker
----------------
On Windows use ``--pool=solo`` to avoid ``billiard`` child-process failures.

    celery -A app.workers.agent_worker.celery_app worker \\
        -Q agent --pool=solo -l info \
        --without-gossip --without-mingle

On Linux / Docker you can use prefork concurrency instead:

    celery -A app.workers.agent_worker.celery_app worker \
        -Q agent --pool=prefork -c 2 -l info \
        --without-gossip --without-mingle
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from typing import Any

from celery import Celery
from celery.utils.log import get_task_logger
from langchain_core.messages import AIMessage

from app.agent.orchestrator import _stringify_content
from app.config.settings import POSTGRES_ASYNC_URL, REDIS_URL

logger = get_task_logger(__name__)


def _normalize_answer_text(answer: str) -> str:
    """Collapse checker-style JSON payloads into plain answer text."""
    text = answer.strip()
    if not text:
        return ""

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return text

    try:
        payload = json.loads(text[start:end + 1])
    except Exception:
        return text

    if not isinstance(payload, dict) or "corrected_answer" not in payload:
        return text

    corrected = str(payload.get("corrected_answer") or "").strip()
    flags = [str(flag) for flag in (payload.get("flags") or []) if str(flag).strip()]
    notes = f"\n\n> **Checker flags**: {'; '.join(flags)}" if flags else ""

    if corrected:
        return corrected + notes
    if flags:
        return notes.lstrip()
    return text


def _is_graph_recursion_error(exc: Exception) -> bool:
    return (
        type(exc).__name__ == "GraphRecursionError"
        or "GRAPH_RECURSION_LIMIT" in str(exc)
        or "Recursion limit" in str(exc)
    )

# ---------------------------------------------------------------------------
# Celery application
# ---------------------------------------------------------------------------

celery_app = Celery(
    "agent",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Keep results for 1 hour
    result_expires=3600,
    # Acknowledge only after the task completes
    task_acks_late=True,
    # One task at a time per worker slot (agent tasks are long-running)
    worker_prefetch_multiplier=1,
    # Surface STARTED state for the API to detect fast
    task_track_started=True,
    enable_utc=True,
    # Fail fast if the broker is unreachable
    broker_transport_options={
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
        "retry_on_timeout": False,
    },
    broker_connection_retry_on_startup=False,
)

# ---------------------------------------------------------------------------
# Internal async implementation
# ---------------------------------------------------------------------------


async def _run_agent_async(
    username: str,
    password: str,
    query: str,
    thread_id: str,
    task_id: str,
    config_override: dict | None = None,
    active_collection_name: str | None = None,
) -> dict:
    """
    Core async implementation.  Creates a per-task PostgreSQL NOTIFY publisher,
    instantiates OrchestratorAgent with a PostgreSQL-backed checkpointer,
    streams the response, and returns the final result dict.

    This is called from the synchronous Celery task via ``asyncio.run()``.
    """
    import asyncpg
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from app.agent.orchestrator import OrchestratorAgent

    channel = f"agent_events_{task_id}"

    pg_notify_conn: asyncpg.Connection = await asyncpg.connect(POSTGRES_ASYNC_URL)

    async def publish(event: dict) -> None:
        await pg_notify_conn.execute(
            "SELECT pg_notify($1, $2)", channel, json.dumps(event)
        )

    agent = None

    try:
        async with AsyncPostgresSaver.from_conn_string(POSTGRES_ASYNC_URL) as checkpointer:
            await checkpointer.setup()
            agent = OrchestratorAgent(
                username=username,
                password=password,
                checkpointer=checkpointer,
                config_override=config_override,
                active_collection_name=active_collection_name,
            )

            token_buffer: list[str] = []

            async for chunk in agent.astream(query=query, thread_id=thread_id):
                if isinstance(chunk, str):
                    # Token from the LLM stream
                    token_buffer.append(chunk)
                    await publish({"type": "token", "content": chunk})
                elif isinstance(chunk, dict):
                    # Structured events from astream: tool_start, sources, interrupt
                    await publish(chunk)

            # Build final response from agent state.
            # Use aget_state to stay fully async — AsyncRedisSaver forbids sync
            # calls from the same thread as the running event loop.
            source_records: list[dict] = []
            state = await agent.graph.aget_state(agent._config(thread_id))
            final_ai_content = ""
            if state and hasattr(state, "values"):
                for rec in state.values.get("source_records", []):
                    source_records.append(dataclasses.asdict(rec))
                final_messages = state.values.get("messages", [])
                last_ai = next(
                    (msg for msg in reversed(final_messages) if isinstance(msg, AIMessage)),
                    None,
                )
                if last_ai:
                    final_ai_content = _stringify_content(last_ai.content)

            answer = _normalize_answer_text(final_ai_content or "".join(token_buffer))
            result = {
                "answer": answer,
                "thread_id": thread_id,
                "source_records": source_records,
                "interrupted": False,
            }

            await publish({"type": "done", "result": result})
            return result

    except Exception as exc:
        if agent is not None and _is_graph_recursion_error(exc):
            fallback_answer = await agent.afallback_answer(query, reason=str(exc))
            result = {
                "answer": fallback_answer,
                "thread_id": thread_id,
                "source_records": [],
                "interrupted": False,
            }
            await publish({"type": "done", "result": result})
            return result

        error_event = {
            "type": "error",
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
        try:
            await publish(error_event)
        except Exception:
            pass  # Don't mask the original exception
        raise
    finally:
        await pg_notify_conn.close()


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="agent.run_agent",
    queue="agent",
    max_retries=0,  # Agent tasks are not retried automatically
)
def task_run_agent(
    self,
    username: str,
    password: str,
    query: str,
    thread_id: str = "default",
    config_override: dict | None = None,
    active_collection_name: str | None = None,
) -> dict:
    """
    Run the SciBot agent for a single query turn.

    This task runs the fully async ``OrchestratorAgent.astream()`` pipeline
    inside a new event loop so it can be dispatched as a normal Celery task.

    While it executes, it publishes incremental events to the Redis pub/sub
    channel ``agent_events:{self.request.id}``.  Callers that want streaming
    output should subscribe to that channel before dispatching this task.
    Callers that only care about the final answer can simply call ``.get()``
    on the returned ``AsyncResult``.

    Parameters
    ----------
    username  : owning user
    password  : user password (used to decrypt per-user config and keys)
    query     : the user's message for this turn
    thread_id : LangGraph thread identifier; use the same value across turns
                to continue a conversation

    Returns
    -------
    dict with keys:
        answer         : str — the full text response
        thread_id      : str — echoed back for convenience
        source_records : list[dict] — serialised SourceRecord dataclasses
        interrupted    : bool — True when the graph hit a HITL interrupt
    """
    task_id: str = self.request.id or "unknown"

    logger.info(
        "task_run_agent start — user=%s thread=%s task=%s query_len=%d",
        username,
        thread_id,
        task_id,
        len(query),
    )

    result = asyncio.run(
        _run_agent_async(
            username=username,
            password=password,
            query=query,
            thread_id=thread_id,
            task_id=task_id,
            config_override=config_override,
            active_collection_name=active_collection_name,
        )
    )

    logger.info(
        "task_run_agent done — user=%s thread=%s task=%s answer_len=%d sources=%d",
        username,
        thread_id,
        task_id,
        len(result.get("answer", "")),
        len(result.get("source_records", [])),
    )

    return result


@celery_app.task(
    bind=True,
    name="agent.resume_agent",
    queue="agent",
    max_retries=0,
)
def task_resume_agent(
    self,
    username: str,
    password: str,
    thread_id: str,
    response: Any,
    active_collection_name: str | None = None,
    config_override: dict | None = None,
) -> dict:
    """
    Resume an interrupted agent run (HITL approval gate).

    Call this after dispatching ``task_run_agent`` received a
    ``{"type": "interrupt"}`` event on the pub/sub channel.

    Parameters
    ----------
    username  : owning user
    password  : user password
    thread_id : same thread_id used for the interrupted task_run_agent call
    response  : value passed back to the interrupt() call — ``True`` to
                approve, ``False`` to reject, or any JSON-serialisable value

    Returns
    -------
    Same dict shape as ``task_run_agent``.
    """
    task_id: str = self.request.id or "unknown"
    channel = f"agent_events:{task_id}"

    async def _resume() -> dict:
        import asyncpg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        from app.agent.orchestrator import OrchestratorAgent

        pg_notify_conn: asyncpg.Connection = await asyncpg.connect(POSTGRES_ASYNC_URL)

        async def publish(event: dict) -> None:
            await pg_notify_conn.execute(
                "SELECT pg_notify($1, $2)", channel, json.dumps(event)
            )

        try:
            async with AsyncPostgresSaver.from_conn_string(POSTGRES_ASYNC_URL) as checkpointer:
                await checkpointer.setup()
                agent = OrchestratorAgent(
                    username=username,
                    password=password,
                    checkpointer=checkpointer,
                    active_collection_name=active_collection_name,
                    config_override=config_override,
                )

                token_buffer: list[str] = []

                async for chunk in agent.astream_resume(
                    response=response, thread_id=thread_id
                ):
                    if isinstance(chunk, str):
                        token_buffer.append(chunk)
                        await publish({"type": "token", "content": chunk})
                    elif isinstance(chunk, dict):
                        await publish(chunk)

                # Build final answer from state (same as _run_agent_async)
                source_records: list[dict] = []
                state = await agent.graph.aget_state(agent._config(thread_id))
                final_ai_content = ""
                if state and hasattr(state, "values"):
                    for rec in state.values.get("source_records", []):
                        source_records.append(dataclasses.asdict(rec))
                    final_messages = state.values.get("messages", [])
                    last_ai = next(
                        (msg for msg in reversed(final_messages) if isinstance(msg, AIMessage)),
                        None,
                    )
                    if last_ai:
                        final_ai_content = _stringify_content(last_ai.content)

                answer = _normalize_answer_text(final_ai_content or "".join(token_buffer))
                result = {
                    "answer": answer,
                    "thread_id": thread_id,
                    "source_records": source_records,
                    "interrupted": False,
                }

                await publish({"type": "done", "result": result})
                return result
        finally:
            await pg_notify_conn.close()

    return asyncio.run(_resume())
