import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.time import utc_now
from services.payments.app.models import Transfer, TransferStatus
from services.payments.app.service import TransferCoordinator


async def recover_stale_transfers(
    factory: async_sessionmaker[AsyncSession],
    coordinator: TransferCoordinator,
    max_age_seconds: int,
    batch_size: int,
) -> int:
    cutoff = utc_now() - timedelta(seconds=max_age_seconds)
    async with factory() as session, session.begin():
        transfer_ids = list(
            (
                await session.scalars(
                    select(Transfer.id)
                    .where(
                        Transfer.status.in_([TransferStatus.PENDING, TransferStatus.PROCESSING]),
                        Transfer.updated_at < cutoff,
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
    for transfer_id in transfer_ids:
        await coordinator.process_transfer(transfer_id)
    return len(transfer_ids)


async def recovery_worker(
    factory: async_sessionmaker[AsyncSession],
    coordinator: TransferCoordinator,
    interval_seconds: float,
    max_age_seconds: int,
    batch_size: int,
) -> None:
    while True:
        await recover_stale_transfers(factory, coordinator, max_age_seconds, batch_size)
        await asyncio.sleep(interval_seconds)
