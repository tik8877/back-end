from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import BadRequestError, NotFoundError
from services.accounts.app.config import get_settings
from services.accounts.app.db import get_session
from services.accounts.app.models import Account, Operation
from services.accounts.app.schemas import AccountResponse, MoneyRequest, OperationResponse, ReservationResponse
from services.accounts.app.service import AccountService, request_digest


router = APIRouter(tags=["accounts"])
Session = Annotated[AsyncSession, Depends(get_session)]


def required_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    if not idempotency_key or len(idempotency_key) > 255:
        raise BadRequestError("IDEMPOTENCY_KEY_REQUIRED", "Заголовок Idempotency-Key обязателен")
    return idempotency_key


def user_from_header(request: Request) -> UUID:
    value = request.headers.get("X-User-Id")
    try:
        return UUID(value or "")
    except ValueError as exc:
        raise BadRequestError("USER_ID_REQUIRED", "Заголовок X-User-Id обязателен") from exc


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(
    session: Session,
    user_id: Annotated[UUID, Depends(user_from_header)],
    key: Annotated[str, Depends(required_key)],
):
    return await AccountService(session, get_settings()).create_account(user_id, key)


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    session: Session,
    user_id: Annotated[UUID, Depends(user_from_header)],
):
    return list((await session.scalars(select(Account).where(Account.user_id == user_id))).all())


@router.get("/accounts/operations/by-key", response_model=OperationResponse)
async def operation_by_key(session: Session, idempotency_key: str = Query(max_length=255)):
    return await AccountService(session, get_settings()).operation_by_key(idempotency_key)


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(account_id: UUID, session: Session):
    account = await session.get(Account, account_id)
    if not account:
        raise NotFoundError("ACCOUNT_NOT_FOUND", "Счёт не найден")
    return account


@router.post("/accounts/{account_id}/deposit", response_model=OperationResponse)
async def deposit(account_id: UUID, body: MoneyRequest, session: Session, key: Annotated[str, Depends(required_key)]):
    return await AccountService(session, get_settings()).deposit(
        account_id, body.amount, key, request_digest(body.model_dump(mode="json"))
    )


@router.post("/accounts/{account_id}/withdraw", response_model=OperationResponse)
async def withdraw(account_id: UUID, body: MoneyRequest, session: Session, key: Annotated[str, Depends(required_key)]):
    return await AccountService(session, get_settings()).withdraw(
        account_id, body.amount, key, request_digest(body.model_dump(mode="json"))
    )


@router.post("/accounts/{account_id}/reserve", response_model=ReservationResponse)
async def reserve(account_id: UUID, body: MoneyRequest, session: Session, key: Annotated[str, Depends(required_key)]):
    return await AccountService(session, get_settings()).reserve(
        account_id, body.amount, key, request_digest(body.model_dump(mode="json"))
    )


@router.post("/accounts/reservations/{reservation_id}/confirm", response_model=ReservationResponse)
async def confirm(reservation_id: UUID, session: Session, key: Annotated[str, Depends(required_key)]):
    return await AccountService(session, get_settings()).finish_reservation(reservation_id, key, True)


@router.post("/accounts/reservations/{reservation_id}/cancel", response_model=ReservationResponse)
async def cancel(reservation_id: UUID, session: Session, key: Annotated[str, Depends(required_key)]):
    return await AccountService(session, get_settings()).finish_reservation(reservation_id, key, False)


@router.post("/accounts/{account_id}/close", response_model=OperationResponse)
async def close(account_id: UUID, session: Session, key: Annotated[str, Depends(required_key)]):
    return await AccountService(session, get_settings()).close_account(account_id, key)


@router.get("/accounts/{account_id}/operations", response_model=list[OperationResponse])
async def operations(account_id: UUID, session: Session, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return list(
        (
            await session.scalars(
                select(Operation)
                .where(Operation.account_id == account_id)
                .order_by(Operation.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
