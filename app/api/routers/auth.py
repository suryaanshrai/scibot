from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import AuthUser, get_current_user
from app.api.models import (
    LoginResponse,
    RegisterRequest,
    UpdatePasswordRequest,
    UpdateUsernameRequest,
)
from app.users.users import AuthError, create_user, update_password, update_username

router = APIRouter()


@router.post("/register", status_code=201)
async def register(req: RegisterRequest) -> dict:
    try:
        await asyncio.to_thread(create_user, req.username, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"username": req.username, "message": "User created successfully"}


@router.post("/login", response_model=LoginResponse)
async def login(user: AuthUser = Depends(get_current_user)) -> LoginResponse:
    return LoginResponse(username=user.username, message="Login successful")


@router.patch("/password", status_code=200)
async def change_password(
    req: UpdatePasswordRequest,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    try:
        await asyncio.to_thread(update_password, user.username, user.password, req.new_password)
    except (AuthError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Password updated successfully"}


@router.patch("/username", status_code=200)
async def change_username(
    req: UpdateUsernameRequest,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    try:
        await asyncio.to_thread(update_username, user.username, user.password, req.new_username)
    except (AuthError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"username": req.new_username, "message": "Username updated successfully"}
