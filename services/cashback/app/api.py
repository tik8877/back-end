from typing import Annotated
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import BadRequestError
from services.cashback.app.db import get_session
from services.cashback.app.models import Accrual, AccrualStatus


router = APIRouter(prefix="/cashback", tags=["cashback"])


def user_header(request: Request) -> UUID:
    try:
        return UUID(request.headers.get("X-User-Id", ""))
    except ValueError as exc:
        raise BadRequestError("USER_ID_REQUIRED", "Заголовок X-User-Id обязателен") from exc


async def _rows(user_id: UUID, status: AccrualStatus, session: AsyncSession):
    return list(
        (
            await session.scalars(
                select(Accrual)
                .where(Accrual.user_id == user_id, Accrual.status == status)
                .order_by(Accrual.created_at.desc())
                .limit(500)
            )
        ).all()
    )


@router.get("/expected")
async def expected(
    user_id: Annotated[UUID, Depends(user_header)],
    session: AsyncSession = Depends(get_session),
):
    rows = await _rows(user_id, AccrualStatus.EXPECTED, session)
    return {"items": rows, "total": str(sum((row.amount for row in rows), Decimal("0.00")))}


@router.get("/credited")
async def credited(
    user_id: Annotated[UUID, Depends(user_header)],
    session: AsyncSession = Depends(get_session),
):
    rows = await _rows(user_id, AccrualStatus.CREDITED, session)
    return {"items": rows, "total": str(sum((row.amount for row in rows), Decimal("0.00")))}
