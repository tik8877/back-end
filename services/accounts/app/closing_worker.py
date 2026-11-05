import asyncio
from datetime import timedelta

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.events import new_event
from common.time import utc_now
from services.accounts.app.models import Account, AccountStatus, Reservation, ReservationStatus


async def close_idle_accounts(
    factory: async_sessionmaker[AsyncSession], idle_days: int, batch_size: int
) -> int:
    cutoff = utc_now() - timedelta(days=idle_days)
    active_reserve = exists().where(
        Reservation.account_id == Account.id,
        Reservation.status == ReservationStatus.ACTIVE,
    )
    async with factory() as session, session.begin():
        accounts = list(
            (
                await session.scalars(
                    select(Account)
                    .where(
                        Account.status != AccountStatus.CLOSED,
                        Account.balance == 0,
                        Account.last_operation_at.is_not(None),
                        Account.last_operation_at < cutoff,
                        ~active_reserve,
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for account in accounts:
            if account.status == AccountStatus.CLOSED:
                continue
            account.status = AccountStatus.CLOSED
            account.version += 1
            session.add(
                new_event(
                    "account.closed",
                    {"account_id": str(account.id), "user_id": str(account.user_id)},
                )
            )
        return len(accounts)


async def closing_worker(
    factory: async_sessionmaker[AsyncSession], interval_seconds: float, idle_days: int, batch_size: int
) -> None:
    while True:
        await close_idle_accounts(factory, idle_days, batch_size)
        await asyncio.sleep(interval_seconds)
