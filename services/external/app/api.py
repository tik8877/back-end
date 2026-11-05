import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import BadRequestError, NotFoundError
from common.time import utc_now
from services.external.app.db import get_session
from services.external.app.models import Integration, SyncJob
from services.external.app.schemas import SyncRequest, SyncResponse


router = APIRouter(prefix="/external", tags=["external"])


def user_header(request: Request) -> UUID:
    try:
        return UUID(request.headers.get("X-User-Id", ""))
    except ValueError as exc:
        raise BadRequestError("USER_ID_REQUIRED", "Заголовок X-User-Id обязателен") from exc


def key_header(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    if not idempotency_key:
        raise BadRequestError("IDEMPOTENCY_KEY_REQUIRED", "Заголовок Idempotency-Key обязателен")
    return idempotency_key


@router.post("/connect")
async def connect(
    user_id: Annotated[UUID, Depends(user_header)],
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        row = await session.scalar(
            select(Integration).where(Integration.user_id == user_id).with_for_update()
        )
        if not row:
            row = Integration(user_id=user_id)
            session.add(row)
            await session.flush()
        row.active = True
        row.disconnected_at = None
        return {"integration_id": str(row.id), "active": True}


@router.post("/disconnect")
async def disconnect(
    user_id: Annotated[UUID, Depends(user_header)],
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        row = await session.scalar(
            select(Integration).where(Integration.user_id == user_id).with_for_update()
        )
        if not row:
            raise NotFoundError("INTEGRATION_NOT_FOUND", "Подключение не найдено")
        row.active = False
        row.disconnected_at = utc_now()
        return {"integration_id": str(row.id), "active": False}


@router.post("/sync", response_model=SyncResponse, status_code=202)
async def start_sync(
    body: SyncRequest,
    user_id: Annotated[UUID, Depends(user_header)],
    key: Annotated[str, Depends(key_header)],
    session: AsyncSession = Depends(get_session),
):
    if body.date_from >= body.date_to:
        raise BadRequestError("INVALID_PERIOD", "Начало периода должно быть раньше окончания")
    digest = hashlib.sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    async with session.begin():
        row = await session.scalar(
            select(SyncJob).where(SyncJob.idempotency_key == key).with_for_update()
        )
        if row:
            if row.request_hash != digest:
                raise BadRequestError("IDEMPOTENCY_KEY_REUSE", "Ключ уже использован")
            return row
        row = SyncJob(
            user_id=user_id,
            idempotency_key=key,
            request_hash=digest,
            date_from=body.date_from,
            date_to=body.date_to,
        )
        session.add(row)
        await session.flush()
        return row


@router.get("/sync/{job_id}", response_model=SyncResponse)
async def sync_status(job_id: UUID, session: AsyncSession = Depends(get_session)):
    row = await session.get(SyncJob, job_id)
    if not row:
        raise NotFoundError("SYNC_JOB_NOT_FOUND", "Задание не найдено")
    return row
