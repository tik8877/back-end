import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.events import new_event
from common.time import utc_now
from services.accounts.app.models import Account, Reservation, ReservationStatus


async def expire_reservations(
    factory: async_sessionmaker[AsyncSession], batch_size: int
) -> int:
    async with factory() as session, session.begin():
        reservations = list(
            (
                await session.scalars(
                    select(Reservation)
                    .where(
                        Reservation.status == ReservationStatus.ACTIVE,
                        Reservation.expires_at < utc_now(),
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for reservation in reservations:
            account = await session.scalar(
                select(Account)
                .where(Account.id == reservation.account_id)
                .with_for_update()
            )
            if account and reservation.status == ReservationStatus.ACTIVE:
                account.available_balance += reservation.amount
                account.version += 1
                reservation.status = ReservationStatus.EXPIRED
                session.add(
                    new_event(
                        "reservation.expired",
                        {
                            "reservation_id": str(reservation.id),
                            "account_id": str(reservation.account_id),
                        },
                    )
                )
        return len(reservations)


async def reservations_worker(
    factory: async_sessionmaker[AsyncSession], interval_seconds: float, batch_size: int
) -> None:
    while True:
        await expire_reservations(factory, batch_size)
        await asyncio.sleep(interval_seconds)
