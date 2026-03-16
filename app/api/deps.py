from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.users.users import AuthError, authenticate

security = HTTPBasic()


@dataclass
class AuthUser:
    username: str
    password: str


async def get_current_user(
    creds: HTTPBasicCredentials = Depends(security),
) -> AuthUser:
    try:
        await asyncio.to_thread(authenticate, creds.username, creds.password)
    except AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return AuthUser(username=creds.username, password=creds.password)
