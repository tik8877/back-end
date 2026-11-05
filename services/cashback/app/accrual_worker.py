import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.time import utc_now
from services.cashback.app.models import Accrual, AccrualStatus, PeriodCredit


RECONCILIATION_ERRORS = Counter(
    "cashback_reconciliation_errors_total",
    "Расхождения при сверке начислений",
)


def period_bounds(now: datetime, seconds: int) -> tuple[datetime, datetime]:
    timestamp = int(now.timestamp())
    start = timestamp - timestamp % seconds - seconds
    return datetime.fromtimestamp(start, UTC), datetime.fromtimestamp(start + seconds, UTC)


async def credit_period(
    factory: async_sessionmaker[AsyncSession], period_seconds: int, batch_size: int
) -> int:
    start, end = period_bounds(utc_now(), period_seconds)
    async with factory() as session, session.begin():
        rows = list(
            (
                await session.scalars(
                    select(Accrual)
                    .where(
                        Accrual.status == AccrualStatus.EXPECTED,
                        Accrual.created_at >= start,
                        Accrual.created_at < end,
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        grouped: dict = {}
        for row in rows:
            grouped.setdefault(row.user_id, []).append(row)
        credited = 0
        for user_id, user_rows in grouped.items():
            if await session.scalar(
                select(PeriodCredit.id).where(
                    PeriodCredit.user_id == user_id,
                    PeriodCredit.period_start == start,
                )
            ):
                continue
            invalid = any(row.amount < 0 or row.amount > row.source_amount for row in user_rows)
            if invalid:
                RECONCILIATION_ERRORS.inc()
                continue
            total = sum((row.amount for row in user_rows), Decimal("0.00"))
            session.add(
                PeriodCredit(
                    user_id=user_id,
                    period_start=start,
                    period_end=end,
                    amount=total,
                )
            )
            for row in user_rows:
                row.status = AccrualStatus.CREDITED
                row.credited_at = utc_now()
                credited += 1
        return credited


async def accrual_worker(
    factory: async_sessionmaker[AsyncSession],
    interval_seconds: float,
    period_seconds: int,
    batch_size: int,
) -> None:
    while True:
        await credit_period(factory, period_seconds, batch_size)
        await asyncio.sleep(interval_seconds)
