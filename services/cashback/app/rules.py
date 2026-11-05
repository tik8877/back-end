from datetime import datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.cashback.app.models import CashbackRule


async def select_rule(
    session: AsyncSession,
    mcc_code: str,
    amount: Decimal,
    occurred_at: datetime,
) -> CashbackRule | None:
    return await session.scalar(
        select(CashbackRule)
        .where(
            CashbackRule.mcc_code == mcc_code,
            CashbackRule.min_amount <= amount,
            CashbackRule.max_amount >= amount,
            CashbackRule.valid_from <= occurred_at,
            or_(CashbackRule.valid_to.is_(None), CashbackRule.valid_to > occurred_at),
        )
        .order_by(CashbackRule.valid_from.desc())
        .limit(1)
    )
