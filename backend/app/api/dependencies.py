from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.auth import User
from app.services.auth import AuthService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


async def get_thread_service(request: Request):
    return request.app.state.thread_service


async def get_agent(request: Request):
    return request.app.state.agent


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証が必要です。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_service.require_user(credentials.credentials)
