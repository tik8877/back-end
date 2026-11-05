from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db import Base
from services.ledger.app.consumer import record_transfer
from services.ledger.app.models import Entry


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    value = async_sessionmaker(engine, expire_on_commit=False)
    yield value
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_event_creates_one_entry(factory):
    payload = {
        "transfer_id": str(uuid4()),
        "debit_account_id": str(uuid4()),
        "credit_account_id": str(uuid4()),
        "amount": "20.00",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    assert await record_transfer(factory, payload) is True
    assert await record_transfer(factory, payload) is False
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(Entry))
    assert count == 1
