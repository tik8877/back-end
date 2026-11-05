from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import BadRequestError, NotFoundError
from services.payments.app.db import get_session
from services.payments.app.models import Transfer
from services.payments.app.schemas import TransferCreate, TransferResponse
from services.payments.app.service import request_digest


router = APIRouter(tags=["payments"])
Session = Annotated[AsyncSession, Depends(get_session)]


def key_header(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    if not idempotency_key or len(idempotency_key) > 255:
        raise BadRequestError("IDEMPOTENCY_KEY_REQUIRED", "Заголовок Idempotency-Key обязателен")
    return idempotency_key


def user_header(request: Request) -> UUID:
    try:
        return UUID(request.headers.get("X-User-Id", ""))
    except ValueError as exc:
        raise BadRequestError("USER_ID_REQUIRED", "Заголовок X-User-Id обязателен") from exc


@router.post("/transfers", response_model=TransferResponse, status_code=201)
async def create_transfer(
    request: Request,
    body: TransferCreate,
    user_id: Annotated[UUID, Depends(user_header)],
    key: Annotated[str, Depends(key_header)],
):
    return await request.app.state.coordinator.create_transfer(
        user_id,
        body.sender_account_id,
        body.receiver_account_id,
        body.amount,
        key,
        request_digest(body.model_dump(mode="json")),
    )


@router.get("/transfers/{transfer_id}", response_model=TransferResponse)
async def get_transfer(transfer_id: UUID, session: Session):
    transfer = await session.get(Transfer, transfer_id)
    if not transfer:
        raise NotFoundError("TRANSFER_NOT_FOUND", "Перевод не найден")
    return transfer


@router.get("/transfers", response_model=list[TransferResponse])
async def find_transfer(session: Session, idempotency_key: str | None = Query(None)):
    query = select(Transfer)
    if idempotency_key:
        query = query.where(Transfer.idempotency_key == idempotency_key)
    return list((await session.scalars(query.order_by(Transfer.created_at.desc()).limit(100))).all())
