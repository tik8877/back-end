from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.ledger.app.config import get_settings
from services.ledger.app.consumer import record_transfer
from services.ledger.app.db import get_session
from services.ledger.app.models import Entry
from services.ledger.app.schemas import BalanceResponse, StatementPage, TransferEvent


router = APIRouter(tags=["ledger"])


@router.post("/internal/events", status_code=202)
async def ingest_event(request: Request, body: TransferEvent):
    created = await record_transfer(
        request.app.state.session_factory,
        body.model_dump(mode="json"),
    )
    return {"accepted": True, "created": created}


@router.get("/statements/{account_id}", response_model=StatementPage)
async def statement(
    account_id: UUID,
    session: AsyncSession = Depends(get_session),
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    cursor_timestamp: datetime | None = None,
    cursor_id: UUID | None = None,
    limit: int = Query(50, ge=1),
):
    settings = get_settings()
    limit = min(limit, settings.statement_max_limit)
    conditions = [
        or_(Entry.debit_account_id == account_id, Entry.credit_account_id == account_id)
    ]
    if from_time:
        conditions.append(Entry.timestamp >= from_time)
    if to_time:
        conditions.append(Entry.timestamp < to_time)
    if cursor_timestamp and cursor_id:
        conditions.append(
            or_(
                Entry.timestamp > cursor_timestamp,
                and_(Entry.timestamp == cursor_timestamp, Entry.id > cursor_id),
            )
        )
    rows = list(
        (
            await session.scalars(
                select(Entry)
                .where(*conditions)
                .order_by(Entry.timestamp, Entry.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    last = items[-1] if items and has_more else None
    return StatementPage(
        items=items,
        next_timestamp=last.timestamp if last else None,
        next_id=last.id if last else None,
    )


@router.get("/balances/{account_id}", response_model=BalanceResponse)
async def balance(account_id: UUID, session: AsyncSession = Depends(get_session)):
    credits = await session.scalar(
        select(func.coalesce(func.sum(Entry.amount), 0)).where(
            Entry.credit_account_id == account_id
        )
    )
    debits = await session.scalar(
        select(func.coalesce(func.sum(Entry.amount), 0)).where(
            Entry.debit_account_id == account_id
        )
    )
    return BalanceResponse(account_id=account_id, balance=Decimal(credits) - Decimal(debits))
