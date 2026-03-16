"""
app.workers.agent_worker — Celery background worker for agent execution.

The ``task_run_agent`` task wraps the async ``OrchestratorAgent.astream()``
method inside a synchronous Celery task so it can be dispatched from any
caller (API, CLI, tests) without needing an event loop in the caller.

Broker + result backend
-----------------------
Uses the ``redis-agent`` Redis container exclusively (port 6380).  This keeps
the agent queue completely isolated from the ingestion queue.

LangGraph checkpointing
-----------------------
Conversation threads persist across worker restarts using
``AsyncRedisSaver`` from ``langgraph-checkpoint-redis``.  The saver connects
to the same ``redis-agent`` Redis instance so that any worker process can
resume any conversation thread.

Streaming via pub/sub
---------------------
While a task runs it continuously publishes events to the Redis pub/sub
channel ``agent_events:{task_id}`` so the API layer can forward them in
real time to WebSocket / SSE clients without polling the result backend:

    {"type": "token",      "content": "<text chunk>"}
    {"type": "tool_start", "tool": "<tool name>"}
    {"type": "sources",    "count": N, "filtered": M}
    {"type": "interrupt",  "payload": {...}}        # HITL gate
    {"type": "done",       "result": {...}}         # final summary

The ``{"type": "done"}`` event is the last message; the channel is then
released.  Subscribers should close their listener after receiving it.

Start the worker
----------------
    celery -A app.workers.agent_worker.celery_app worker \\
        -Q agent -c 2 -l info \\
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

from app.config.settings import REDIS_AGENT_URL

logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# Celery application
# ---------------------------------------------------------------------------

celery_app = Celery(
    "agent",
    broker=REDIS_AGENT_URL,
    backend=REDIS_AGENT_URL,
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
) -> dict:
    """
    Core async implementation.  Creates a per-task Redis pub/sub publisher,
    instantiates OrchestratorAgent with a Redis-backed checkpointer, streams
    the response, and returns the final result dict.

    This is called from the synchronous Celery task via ``asyncio.run()``.
    """
    import redis.asyncio as aioredis
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

    from app.agent.orchestrator import OrchestratorAgent

    channel = f"agent_events:{task_id}"

    redis_client: aioredis.Redis = aioredis.from_url(
        REDIS_AGENT_URL, decode_responses=False
    )

    async def publish(event: dict) -> None:
        await redis_client.publish(channel, json.dumps(event))

    try:
        async with AsyncRedisSaver.from_conn_string(REDIS_AGENT_URL) as checkpointer:
            agent = OrchestratorAgent(
                username=username,
                password=password,
                checkpointer=checkpointer,
                config_override=config_override,
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
            if state and hasattr(state, "values"):
                for rec in state.values.get("source_records", []):
                    source_records.append(dataclasses.asdict(rec))

            answer = "".join(token_buffer)
            result = {
                "answer": answer,
                "thread_id": thread_id,
                "source_records": source_records,
                "interrupted": False,
            }

            await publish({"type": "done", "result": result})
            return result

    except Exception as exc:
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
        await redis_client.aclose()


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
        import redis.asyncio as aioredis
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        from app.agent.orchestrator import OrchestratorAgent

        redis_client: aioredis.Redis = aioredis.from_url(
            REDIS_AGENT_URL, decode_responses=False
        )

        try:
            async with AsyncRedisSaver.from_conn_string(REDIS_AGENT_URL) as checkpointer:
                agent = OrchestratorAgent(
                    username=username,
                    password=password,
                    checkpointer=checkpointer,
                )

                agent_response = await agent.resume(
                    response=response, thread_id=thread_id
                )

                source_records = [
                    dataclasses.asdict(r) for r in agent_response.sources
                ]
                result = {
                    "answer": agent_response.answer,
                    "thread_id": thread_id,
                    "source_records": source_records,
                    "interrupted": agent_response.interrupted,
                }

                await redis_client.publish(
                    channel, json.dumps({"type": "done", "result": result})
                )
                return result
        finally:
            await redis_client.aclose()

    return asyncio.run(_resume())
