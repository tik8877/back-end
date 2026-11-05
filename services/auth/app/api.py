from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import BadRequestError
from services.auth.app.config import get_settings
from services.auth.app.db import get_session
from services.auth.app.schemas import LoginRequest, RegisterRequest, RegisterResponse, TokenPair, TokenRequest
from services.auth.app.security import jwks
from services.auth.app.service import AuthService, request_digest


router = APIRouter(tags=["auth"])


def key_header(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    if not idempotency_key or len(idempotency_key) > 255:
        raise BadRequestError("IDEMPOTENCY_KEY_REQUIRED", "Заголовок Idempotency-Key обязателен")
    return idempotency_key


def service(request: Request, session: AsyncSession) -> AuthService:
    redis: Redis = request.app.state.redis
    return AuthService(session, redis, get_settings())


@router.post("/auth/register", response_model=RegisterResponse)
async def register(
    request: Request,
    body: RegisterRequest,
    key: Annotated[str, Depends(key_header)],
    session: AsyncSession = Depends(get_session),
):
    digest = request_digest(body.model_dump())
    return await service(request, session).register(body.login, body.password, key, digest)


@router.post("/auth/login", response_model=TokenPair)
async def login(
    request: Request,
    body: LoginRequest,
    key: Annotated[str, Depends(key_header)],
    session: AsyncSession = Depends(get_session),
):
    ip = request.headers.get("X-Client-Ip") or (
        request.client.host if request.client else "unknown"
    )
    digest = request_digest(body.model_dump())
    return await service(request, session).login(body.login, body.password, ip, key, digest)


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(
    request: Request,
    body: TokenRequest,
    key: Annotated[str, Depends(key_header)],
    session: AsyncSession = Depends(get_session),
):
    digest = request_digest({"refresh_token_hash": request_digest({"token": body.refresh_token})})
    return await service(request, session).refresh(body.refresh_token, key, digest)


@router.post("/auth/logout")
async def logout(
    request: Request,
    body: TokenRequest,
    key: Annotated[str, Depends(key_header)],
    session: AsyncSession = Depends(get_session),
):
    digest = request_digest({"refresh_token_hash": request_digest({"token": body.refresh_token})})
    return await service(request, session).logout(body.refresh_token, key, digest)


@router.get("/.well-known/jwks.json")
async def public_keys():
    return jwks(get_settings())
