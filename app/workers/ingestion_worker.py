"""
app.workers.ingestion_worker — Celery background worker for vector ingestion.

Each ingestion task runs the heavy CPU/IO work (document splitting, embedding,
vector store writes) in a dedicated worker process so the API process stays free.

Broker + result backend
-----------------------
Uses the ``redis-ingestion`` Redis container exclusively (port 6379).  This
keeps the ingestion queue completely isolated from the agent queue.

Tasks
-----
task_ingest_collection       — full ingest of all sources in a collection
task_ingest_new_sources      — idempotent partial ingest (only un-ingested sources)
task_update_store            — re-ingest specific sources (delete-then-reingest)
task_delete_collection_vectors — wipe vectors for a collection from the store

Retry strategy
--------------
Transient errors (connection resets, temporary store unavailability, …) trigger
an automatic retry with an exponential-like back-off: 10 s, 20 s, 30 s.

``StoreSettingsDriftError`` is intentionally NOT retried; it signals a logical
conflict (e.g. the embedding model changed after data was ingested) that
requires human intervention — calling ``task_delete_collection_vectors`` first
and then re-ingesting.

Start the worker
----------------
On Windows use ``--pool=solo`` to avoid ``billiard`` shared-memory /
``WinError 5`` failures.

    celery -A app.workers.ingestion_worker.celery_app worker \\
        -Q ingestion --pool=solo -l info \
        --without-gossip --without-mingle

On Linux / Docker you can use prefork concurrency instead:

    celery -A app.workers.ingestion_worker.celery_app worker \
        -Q ingestion --pool=prefork -c 4 -l info \
        --without-gossip --without-mingle
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Celery
from celery.utils.log import get_task_logger

from app.config.settings import REDIS_URL
from app.sources.collection import (
    create_collection as col_create,
    update_collection as col_update,
)
from app.storage.ingestion import (
    StoreSettingsDriftError,
    delete_collection_vectors,
    ingest_collection,
    ingest_new_sources,
    update_store,
)
from app.users.collections_db import load_collection, update_collection_data

logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# Celery application
# ---------------------------------------------------------------------------

celery_app = Celery(
    "ingestion",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    # Use JSON throughout — no pickle, no security surprises
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Keep results for 1 hour (API can poll within that window)
    result_expires=3600,
    # Acknowledge only after the task completes, so a worker crash re-queues
    task_acks_late=True,
    # Disable prefetch so heavy tasks don't pile up on a single worker
    worker_prefetch_multiplier=1,
    # Surface STARTED state in the result backend
    task_track_started=True,
    # Timezone
    enable_utc=True,
    # Fail fast if the broker is unreachable (avoids hanging the API process)
    broker_transport_options={
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
        "retry_on_timeout": False,
    },
    broker_connection_retry_on_startup=False,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RETRY_DELAYS = (10, 20, 30)  # seconds between retries


def _should_retry(exc: Exception) -> bool:
    """Return True for errors that are worth retrying automatically."""
    return not isinstance(exc, (StoreSettingsDriftError, KeyError, ValueError))


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="ingestion.ingest_collection",
    queue="ingestion",
    max_retries=3,
)
def task_ingest_collection(
    self,
    username: str,
    collection_name: str,
    config: dict[str, Any] | None = None,
    password: str | None = None,
) -> dict:
    """
    Ingest ALL sources in *collection_name* into the vector store.

    Parameters
    ----------
    username        : owning user
    collection_name : collection to ingest
    config          : optional config overrides (JSON-serialisable dict)
    password        : user password for per-user config decryption

    Returns
    -------
    IngestResult as a plain dict (JSON-serialisable).
    """
    try:
        result = ingest_collection(
            username=username,
            collection_name=collection_name,
            config=config,
            password=password,
        )
        logger.info(
            "ingest_collection done — user=%s collection=%s sources=%d chunks=%d",
            username,
            collection_name,
            result["ingested_sources"],
            result["total_chunks"],
        )
        return dict(result)
    except StoreSettingsDriftError:
        # Not retryable — propagate immediately so the caller sees the error
        raise
    except Exception as exc:
        retry_index = self.request.retries  # 0-based
        delay = _RETRY_DELAYS[min(retry_index, len(_RETRY_DELAYS) - 1)]
        if _should_retry(exc):
            logger.warning(
                "ingest_collection transient error (retry %d/3): %s",
                retry_index + 1,
                exc,
            )
            raise self.retry(exc=exc, countdown=delay)
        raise


@celery_app.task(
    bind=True,
    name="ingestion.ingest_new_sources",
    queue="ingestion",
    max_retries=3,
)
def task_ingest_new_sources(
    self,
    username: str,
    collection_name: str,
    config: dict[str, Any] | None = None,
    password: str | None = None,
) -> dict:
    """
    Ingest only sources that have not yet been ingested (``ingested_at is null``).

    This is the safe, idempotent variant to call whenever new sources are added
    to an existing collection — it never double-ingests already-processed sources.

    Returns
    -------
    IngestResult as a plain dict.
    """
    try:
        result = ingest_new_sources(
            username=username,
            collection_name=collection_name,
            config=config,
            password=password,
        )
        logger.info(
            "ingest_new_sources done — user=%s collection=%s sources=%d chunks=%d",
            username,
            collection_name,
            result["ingested_sources"],
            result["total_chunks"],
        )
        return dict(result)
    except StoreSettingsDriftError:
        raise
    except Exception as exc:
        retry_index = self.request.retries
        delay = _RETRY_DELAYS[min(retry_index, len(_RETRY_DELAYS) - 1)]
        if _should_retry(exc):
            logger.warning(
                "ingest_new_sources transient error (retry %d/3): %s",
                retry_index + 1,
                exc,
            )
            raise self.retry(exc=exc, countdown=delay)
        raise


@celery_app.task(
    bind=True,
    name="ingestion.update_store",
    queue="ingestion",
    max_retries=3,
)
def task_update_store(
    self,
    username: str,
    collection_name: str,
    source_ids: list[str],
    config: dict[str, Any] | None = None,
    password: str | None = None,
) -> dict:
    """
    Re-ingest specific sources identified by their ``source_id``.

    Deletes the existing vectors for those sources first, then re-ingests from
    the on-disk pkl files.  Use this to apply embedding model changes to a
    subset of sources without wiping the whole collection.

    Parameters
    ----------
    source_ids : list of ``source_id`` strings, e.g. ``["arxiv:1706.03762"]``

    Returns
    -------
    IngestResult as a plain dict.
    """
    try:
        result = update_store(
            username=username,
            collection_name=collection_name,
            source_ids=source_ids,
            config=config,
            password=password,
        )
        logger.info(
            "update_store done — user=%s collection=%s sources=%d chunks=%d",
            username,
            collection_name,
            result["ingested_sources"],
            result["total_chunks"],
        )
        return dict(result)
    except StoreSettingsDriftError:
        raise
    except Exception as exc:
        retry_index = self.request.retries
        delay = _RETRY_DELAYS[min(retry_index, len(_RETRY_DELAYS) - 1)]
        if _should_retry(exc):
            logger.warning(
                "update_store transient error (retry %d/3): %s",
                retry_index + 1,
                exc,
            )
            raise self.retry(exc=exc, countdown=delay)
        raise


@celery_app.task(
    bind=True,
    name="ingestion.delete_collection_vectors",
    queue="ingestion",
    max_retries=3,
)
def task_delete_collection_vectors(
    self,
    username: str,
    collection_name: str,
    config: dict[str, Any] | None = None,
    password: str | None = None,
) -> dict:
    """
    Remove ALL vectors for *collection_name* from the vector store.

    This must be called before a full re-ingest when the embedding model or
    distance function has changed (``StoreSettingsDriftError`` scenario).

    Returns
    -------
    ``{"status": "deleted", "username": ..., "collection_name": ...}``
    """
    try:
        delete_collection_vectors(
            username=username,
            collection_name=collection_name,
            config=config,
            password=password,
        )
        logger.info(
            "delete_collection_vectors done — user=%s collection=%s",
            username,
            collection_name,
        )
        return {
            "status": "deleted",
            "username": username,
            "collection_name": collection_name,
        }
    except Exception as exc:
        retry_index = self.request.retries
        delay = _RETRY_DELAYS[min(retry_index, len(_RETRY_DELAYS) - 1)]
        if _should_retry(exc):
            logger.warning(
                "delete_collection_vectors transient error (retry %d/3): %s",
                retry_index + 1,
                exc,
            )
            raise self.retry(exc=exc, countdown=delay)
        raise


@celery_app.task(
    bind=True,
    name="ingestion.create_and_ingest_collection",
    queue="ingestion",
    max_retries=3,
)
def task_create_and_ingest_collection(
    self,
    username: str,
    collection_name: str,
    sources: dict,
    config: dict[str, Any] | None = None,
    password: str | None = None,
) -> dict:
    """
    Create a collection from *sources* (download + pickle) then immediately
    ingest all sources into the vector store.

    This combined task keeps the entire heavy pipeline in the worker so the
    API can return 202 Accepted immediately instead of blocking while papers
    are fetched, transcripts downloaded, etc.
    """
    try:
        result = col_create(
            username=username,
            collection_name=collection_name,
            sources=sources,  # type: ignore[arg-type]
            config=config,
            password=password,
        )
        actual_name = result["collection_name"]

        # Tag the collection record with our task ID so the API can poll status.
        data = load_collection(username, actual_name)
        if data is not None:
            data["ingestion_task_id"] = self.request.id
            update_collection_data(username, actual_name, data)

        ingest_result = ingest_new_sources(
            username=username,
            collection_name=actual_name,
            config=config,
            password=password,
        )
        load_errors = result["load_errors"]
        dynamic_count = len(
            sources.get("dynamic_sources") or sources.get("dynamic_data_sources") or []
        )
        logger.info(
            "create_and_ingest done — user=%s collection=%s sources=%d chunks=%d dynamic=%d",
            username,
            actual_name,
            ingest_result["ingested_sources"],
            ingest_result["total_chunks"],
            dynamic_count,
        )
        if load_errors:
            logger.warning(
                "create_and_ingest load_errors — user=%s collection=%s errors=%s",
                username,
                actual_name,
                load_errors,
            )
        return {
            "collection_name": actual_name,
            "load_errors": load_errors,
            **dict(ingest_result),
        }
    except StoreSettingsDriftError:
        raise
    except Exception as exc:
        retry_index = self.request.retries
        delay = _RETRY_DELAYS[min(retry_index, len(_RETRY_DELAYS) - 1)]
        if _should_retry(exc):
            logger.warning(
                "create_and_ingest transient error (retry %d/3): %s",
                retry_index + 1,
                exc,
            )
            raise self.retry(exc=exc, countdown=delay)
        raise


@celery_app.task(
    bind=True,
    name="ingestion.update_and_ingest_collection",
    queue="ingestion",
    max_retries=3,
)
def task_update_and_ingest_collection(
    self,
    username: str,
    collection_name: str,
    sources: dict,
    config: dict[str, Any] | None = None,
    password: str | None = None,
) -> dict:
    """
    Append *sources* to an existing collection (download + pickle) then ingest
    only the newly added sources into the vector store.
    """
    try:
        result = col_update(
            username=username,
            collection_name=collection_name,
            new_sources=sources,  # type: ignore[arg-type]
            config=config,
            password=password,
        )

        # Tag with current task ID.
        data = load_collection(username, collection_name)
        if data is not None:
            data["ingestion_task_id"] = self.request.id
            update_collection_data(username, collection_name, data)

        ingest_result = ingest_new_sources(
            username=username,
            collection_name=collection_name,
            config=config,
            password=password,
        )
        load_errors = result["load_errors"]
        dynamic_count = len(
            sources.get("dynamic_sources") or sources.get("dynamic_data_sources") or []
        )
        logger.info(
            "update_and_ingest done — user=%s collection=%s sources=%d chunks=%d dynamic=%d",
            username,
            collection_name,
            ingest_result["ingested_sources"],
            ingest_result["total_chunks"],
            dynamic_count,
        )
        if load_errors:
            logger.warning(
                "update_and_ingest load_errors — user=%s collection=%s errors=%s",
                username,
                collection_name,
                load_errors,
            )
        return {
            "collection_name": collection_name,
            "load_errors": load_errors,
            **dict(ingest_result),
        }
    except StoreSettingsDriftError:
        raise
    except Exception as exc:
        retry_index = self.request.retries
        delay = _RETRY_DELAYS[min(retry_index, len(_RETRY_DELAYS) - 1)]
        if _should_retry(exc):
            logger.warning(
                "update_and_ingest transient error (retry %d/3): %s",
                retry_index + 1,
                exc,
            )
            raise self.retry(exc=exc, countdown=delay)
        raise
