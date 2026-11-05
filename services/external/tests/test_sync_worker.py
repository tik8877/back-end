from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db import Base
from services.external.app.config import Settings
from services.external.app.everypay_client import SourcePage, SourceUnavailable
from services.external.app.models import ExternalTransaction, SyncJob, SyncStatus
from services.external.app.sync_worker import process_next_page


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    value = async_sessionmaker(engine, expire_on_commit=False)
    yield value
    await engine.dispose()


class Source:
    async def fetch_page(self, *args):
        return SourcePage(
            items=[
                {
                    "id": "ext-1",
                    "account_id": str(uuid4()),
                    "amount": "12.00",
                    "currency": "RUB",
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
            ],
            next_cursor=None,
            total_pages=1,
        )


@pytest.mark.asyncio
async def test_page_is_saved_and_job_completed(factory):
    job_id = uuid4()
    async with factory() as session, session.begin():
        session.add(
            SyncJob(
                id=job_id,
                user_id=uuid4(),
                idempotency_key="sync",
                request_hash="x" * 64,
                date_from=datetime.now(UTC) - timedelta(days=1),
                date_to=datetime.now(UTC),
            )
        )
    assert await process_next_page(factory, Source(), Settings()) is True
    async with factory() as session:
        job = await session.get(SyncJob, job_id)
        transaction = await session.scalar(select(ExternalTransaction))
    assert job.status == SyncStatus.COMPLETED
    assert transaction.external_id == "ext-1"
