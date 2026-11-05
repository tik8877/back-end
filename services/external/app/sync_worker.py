import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.events import new_event
from common.time import utc_now
from services.external.app.config import Settings
from services.external.app.everypay_client import EveryPayClient, SourceUnavailable
from services.external.app.models import ExternalTransaction, SyncJob, SyncStatus


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def process_next_page(
    factory: async_sessionmaker[AsyncSession],
    client: EveryPayClient,
    settings: Settings,
) -> bool:
    async with factory() as session, session.begin():
        job = await session.scalar(
            select(SyncJob)
            .where(
                SyncJob.status.in_([SyncStatus.PENDING, SyncStatus.RUNNING]),
                or_(SyncJob.next_attempt_at.is_(None), SyncJob.next_attempt_at <= utc_now()),
            )
            .order_by(SyncJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not job:
            return False
        job.status = SyncStatus.RUNNING
        try:
            page = await client.fetch_page(
                job.date_from, job.date_to, job.last_processed_cursor
            )
        except SourceUnavailable:
            job.error = "SOURCE_UNAVAILABLE"
            job.failure_count += 1
            wait_seconds = min(
                settings.external_wait_base_seconds * (2 ** (job.failure_count - 1)),
                settings.external_wait_max_seconds,
            )
            job.next_attempt_at = utc_now() + timedelta(seconds=wait_seconds)
            return True
        saved = 0
        for item in page.items[: settings.sync_batch_size]:
            external_id = str(item["id"])
            digest = payload_hash(item)
            current = await session.scalar(
                select(ExternalTransaction)
                .where(ExternalTransaction.external_id == external_id)
                .order_by(ExternalTransaction.version.desc())
                .limit(1)
            )
            if current and current.payload_hash == digest:
                continue
            version = current.version + 1 if current else 1
            session.add(
                ExternalTransaction(
                    external_id=external_id,
                    sync_job_id=job.id,
                    account_id=UUID(str(item["account_id"])),
                    amount=Decimal(str(item["amount"])),
                    currency=str(item["currency"]),
                    occurred_at=datetime.fromisoformat(str(item["occurred_at"])),
                    raw_payload=item,
                    payload_hash=digest,
                    version=version,
                )
            )
            saved += 1
        job.last_processed_cursor = page.next_cursor
        job.total_pages = page.total_pages
        job.processed_pages += 1
        job.error = None
        job.failure_count = 0
        job.next_attempt_at = None
        if page.next_cursor is None:
            job.status = SyncStatus.COMPLETED
            job.completed_at = utc_now()
        session.add(
            new_event(
                "external.transactions_synced",
                {
                    "job_id": str(job.id),
                    "user_id": str(job.user_id),
                    "saved": saved,
                    "completed": job.status == SyncStatus.COMPLETED,
                },
            )
        )
        return True


async def sync_worker(
    factory: async_sessionmaker[AsyncSession],
    client: EveryPayClient,
    settings: Settings,
) -> None:
    while True:
        worked = await process_next_page(factory, client, settings)
        if not worked:
            await asyncio.sleep(settings.sync_scan_interval_seconds)
