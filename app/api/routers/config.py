from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import AuthUser, get_current_user
from app.api.models import UserConfigResponse, UserConfigUpdate
from app.config.embedding_model import list_embeddings
from app.config.llm_model import list_llms
from app.config.store import list_stores
from app.users.config import get_user_config, set_user_config, update_user_config
from app.users.users import AuthError

router = APIRouter()


@router.get("/options")
async def get_options(_: AuthUser = Depends(get_current_user)) -> dict:
    """Return all supported LLM providers/models, embedding providers/models, and vector stores."""
    return {
        "llms": list_llms(),
        "embeddings": list_embeddings(),
        "stores": list_stores(),
    }


@router.get("", response_model=UserConfigResponse)
async def get_config(user: AuthUser = Depends(get_current_user)) -> UserConfigResponse:
    try:
        cfg = await asyncio.to_thread(get_user_config, user.username, user.password)
    except (AuthError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return UserConfigResponse(**cfg)


@router.put("", response_model=UserConfigResponse)
async def replace_config(
    body: UserConfigUpdate,
    user: AuthUser = Depends(get_current_user),
) -> UserConfigResponse:
    try:
        new_cfg = body.model_dump(exclude_none=True)
        await asyncio.to_thread(set_user_config, user.username, user.password, new_cfg)
        cfg = await asyncio.to_thread(get_user_config, user.username, user.password)
    except (AuthError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return UserConfigResponse(**cfg)


@router.patch("", response_model=UserConfigResponse)
async def patch_config(
    body: UserConfigUpdate,
    user: AuthUser = Depends(get_current_user),
) -> UserConfigResponse:
    try:
        updates = body.model_dump(exclude_none=True)
        cfg = await asyncio.to_thread(update_user_config, user.username, user.password, updates)
    except (AuthError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return UserConfigResponse(**cfg)
