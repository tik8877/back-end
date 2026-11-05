from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db import Base
from services.cashback.app.consumer import apply_transaction
from services.cashback.app.models import Accrual, CashbackRule


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    value = async_sessionmaker(engine, expire_on_commit=False)
    async with value() as session, session.begin():
        session.add(
            CashbackRule(
                mcc_code="5411",
                min_amount=Decimal("0"),
                max_amount=Decimal("10000"),
                percent=Decimal("5"),
                valid_from=datetime.now(UTC) - timedelta(days=1),
                version="v1",
            )
        )
    yield value
    await engine.dispose()


@pytest.mark.asyncio
async def test_transaction_is_accrued_once(factory):
    payload = {
        "event_type": "transaction.created",
        "transaction_id": str(uuid4()),
        "user_id": str(uuid4()),
        "account_id": str(uuid4()),
        "amount": "100.00",
        "mcc_code": "5411",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    assert await apply_transaction(factory, payload) is True
    assert await apply_transaction(factory, payload) is False
    async with factory() as session:
        row = await session.scalar(select(Accrual))
        count = await session.scalar(select(func.count()).select_from(Accrual))
    assert count == 1
    assert row.amount == Decimal("5.00")
