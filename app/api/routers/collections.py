from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status

from app.api.deps import AuthUser, get_current_user
from app.api.models import (
    AddSourcesRequest,
    CollectionDetail,
    CollectionSourcesIn,
    CollectionSummary,
    CreateCollectionRequest,
    IngestRequest,
    IngestStatusResponse,
)
from app.sources.collection import (
    delete_collection as col_delete,
    get_collection as col_get,
    list_collections as col_list,
)
from app.users.collections_db import load_collection, update_collection_data
from app.workers.ingestion_worker import (
    celery_app as ingestion_celery_app,
    task_create_and_ingest_collection,
    task_ingest_collection,
    task_ingest_new_sources,
    task_update_and_ingest_collection,
    task_update_store,
)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_collection_sources(src: CollectionSourcesIn) -> dict:
    out: dict = {}
    if src.papers:
        out["papers"] = [s.model_dump(exclude_none=True) for s in src.papers]
    if src.youtube:
        entries = []
        for s in src.youtube:
            d: dict[str, Any] = {"url": s.url}
            if s.language:
                d["language"] = [s.language]
            entries.append(d)
        out["youtube"] = entries
    if src.github:
        out["github"] = [s.model_dump(exclude_none=True) for s in src.github]
    if src.webpages:
        out["webpages"] = [s.model_dump(exclude_none=True) for s in src.webpages]
    if src.videos:
        out["videos"] = [s.model_dump(exclude_none=True) for s in src.videos]
    if src.audios:
        out["audios"] = [s.model_dump(exclude_none=True) for s in src.audios]
    if src.images:
        out["images"] = [s.model_dump(exclude_none=True) for s in src.images]
    if src.dynamic_data_sources:
        out["dynamic_data_sources"] = [s.model_dump(exclude_none=True) for s in src.dynamic_data_sources]
    return out


def _store_task_id(username: str, collection_name: str, task_id: str) -> None:
    data = load_collection(username, collection_name)
    if data is not None:
        data["ingestion_task_id"] = task_id
        update_collection_data(username, collection_name, data)


def _build_detail(data: dict, task_status: str | None = None) -> CollectionDetail:
    source_keys = (
        "papers", "youtube", "github_repos", "webpages",
        "videos", "audios", "images", "dynamic_data_sources",
    )
    sources = {k: data.get(k, []) for k in source_keys}
    return CollectionDetail(
        collection_name=data.get("collection_name", ""),
        username=data.get("username", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        sources=sources,
        vector_collection=data.get("vector_collection"),
        ingestion_task_id=data.get("ingestion_task_id"),
        ingestion_task_status=task_status,
    )


def _build_ingest_status(task_id: str) -> IngestStatusResponse:
    r = AsyncResult(task_id, app=ingestion_celery_app)
    task_status = r.status.lower()
    result_data = None
    error = None

    if r.status == "SUCCESS":
        result_data = r.result if isinstance(r.result, dict) else {"raw": str(r.result)}
    elif r.status == "FAILURE":
        error = str(r.result)

    return IngestStatusResponse(task_id=task_id, status=task_status, result=result_data, error=error)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=202)
async def create_collection(
    req: CreateCollectionRequest,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    collection_name = req.collection_name or uuid4().hex
    sources = dict(_to_collection_sources(req.sources))
    try:
        task = await asyncio.to_thread(
            task_create_and_ingest_collection.delay,
            user.username, collection_name, sources, req.config, user.password,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ingestion broker unavailable: {exc}")
    return {"collection_name": collection_name, "task_id": task.id}


@router.get("", response_model=list[CollectionSummary])
async def list_collections(
    user: AuthUser = Depends(get_current_user),
) -> list[CollectionSummary]:
    summaries = await asyncio.to_thread(col_list, user.username)
    return [CollectionSummary(**s) for s in summaries]


@router.get("/{name}", response_model=CollectionDetail)
async def get_collection(
    name: str,
    user: AuthUser = Depends(get_current_user),
) -> CollectionDetail:
    try:
        data = await asyncio.to_thread(col_get, user.username, name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")

    task_id = data.get("ingestion_task_id")
    task_status = None
    if task_id:
        r = AsyncResult(task_id, app=ingestion_celery_app)
        task_status = r.status.lower()

    return _build_detail(data, task_status)


@router.patch("/{name}", status_code=202)
async def add_sources(
    name: str,
    req: AddSourcesRequest,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    # Quick existence check — the heavy lifting goes to the worker
    try:
        await asyncio.to_thread(col_get, user.username, name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")

    sources = dict(_to_collection_sources(req.sources))
    try:
        task = await asyncio.to_thread(
            task_update_and_ingest_collection.delay,
            user.username, name, sources, req.config, user.password,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ingestion broker unavailable: {exc}")
    return {"collection_name": name, "task_id": task.id}


@router.delete("/{name}", status_code=204)
async def delete_collection(
    name: str,
    user: AuthUser = Depends(get_current_user),
) -> None:
    try:
        await asyncio.to_thread(col_delete, user.username, name, password=user.password)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")


@router.post("/{name}/files", status_code=202)
async def upload_files(
    name: str,
    files: list[UploadFile],
    user: AuthUser = Depends(get_current_user),
) -> dict:
    # Ensure collection exists
    try:
        await asyncio.to_thread(col_get, user.username, name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")

    uploads_dir = Path("app") / "data" / user.username / name / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    paper_sources = []
    dynamic_sources = []
    for file in files:
        safe_name = Path(file.filename).name if file.filename else f"upload_{len(paper_sources)}"
        dest = uploads_dir / safe_name
        dest.write_bytes(await file.read())
        ext = dest.suffix.lower()
        if ext in {".csv", ".json"}:
            relative_path = str(Path(name) / "uploads" / safe_name).replace("\\", "/")
            dynamic_sources.append({
                "source_type": ext.lstrip("."),
                "file_path": relative_path,
            })
        else:
            paper_sources.append({"url_or_path": str(dest.resolve())})

    # File bytes are on disk — dispatch worker to load + embed in background
    sources = {}
    if paper_sources:
        sources["papers"] = paper_sources
    if dynamic_sources:
        sources["dynamic_data_sources"] = dynamic_sources
    try:
        task = await asyncio.to_thread(
            task_update_and_ingest_collection.delay,
            user.username, name, sources, None, user.password,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ingestion broker unavailable: {exc}")
    return {"uploaded": len(files), "task_id": task.id}


@router.post("/{name}/ingest", status_code=202)
async def trigger_ingest(
    name: str,
    req: IngestRequest | None = None,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    # Ensure collection exists
    try:
        await asyncio.to_thread(col_get, user.username, name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")

    cfg = req.config if req else None
    source_ids = req.source_ids if req else None

    try:
        if source_ids:
            task = await asyncio.to_thread(task_update_store.delay, user.username, name, source_ids, cfg, user.password)
        else:
            task = await asyncio.to_thread(task_ingest_collection.delay, user.username, name, cfg, user.password)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ingestion broker unavailable: {exc}")
    await asyncio.to_thread(_store_task_id, user.username, name, task.id)
    return {"collection_name": name, "task_id": task.id}


@router.get("/{name}/ingest-status", response_model=IngestStatusResponse)
async def get_ingest_status(
    name: str,
    task_id: str | None = Query(default=None),
    user: AuthUser = Depends(get_current_user),
) -> IngestStatusResponse:
    try:
        data = await asyncio.to_thread(col_get, user.username, name)
    except KeyError:
        if task_id:
            return _build_ingest_status(task_id)
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")

    effective_task_id = data.get("ingestion_task_id") or task_id
    if not effective_task_id:
        return IngestStatusResponse(task_id="", status="not_started")

    return _build_ingest_status(effective_task_id)
