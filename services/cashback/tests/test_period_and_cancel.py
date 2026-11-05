from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db import Base
from common.time import utc_now
from services.cashback.app.accrual_worker import credit_period, period_bounds
from services.cashback.app.consumer import apply_transaction
from services.cashback.app.models import Accrual, AccrualStatus, CashbackRule, PeriodCredit


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    value = async_sessionmaker(engine, expire_on_commit=False)
    yield value
    await engine.dispose()


@pytest.mark.asyncio
async def test_completed_period_is_credited(factory):
    start, _ = period_bounds(utc_now(), 60)
    async with factory() as session, session.begin():
        session.add(
            CashbackRule(
                mcc_code="5411",
                min_amount=Decimal("0"),
                max_amount=Decimal("1000"),
                percent=Decimal("5"),
                valid_from=start - timedelta(days=1),
                version="v1",
            )
        )
    payload = {
        "event_type": "transaction.created",
        "transaction_id": str(uuid4()),
        "user_id": str(uuid4()),
        "account_id": str(uuid4()),
        "amount": "100.00",
        "mcc_code": "5411",
        "timestamp": (start + timedelta(seconds=1)).isoformat(),
    }
    await apply_transaction(factory, payload)
    assert await credit_period(factory, 60, 100) == 1
    async with factory() as session:
        accrual = await session.scalar(select(Accrual))
        credit = await session.scalar(select(PeriodCredit))
    assert accrual.status == AccrualStatus.CREDITED
    assert credit.amount == Decimal("5.00")


@pytest.mark.asyncio
async def test_cancel_before_purchase_prevents_expected_amount(factory):
    transaction_id = uuid4()
    base = {
        "transaction_id": str(transaction_id),
        "user_id": str(uuid4()),
        "account_id": str(uuid4()),
        "amount": "100.00",
        "timestamp": utc_now().isoformat(),
    }
    await apply_transaction(
        factory,
        {**base, "event_type": "transaction.cancelled", "cashback": "5.00"},
    )
    async with factory() as session:
        cancellation = await session.scalar(select(Accrual))
    assert cancellation.amount == Decimal("-5.00")
    assert cancellation.status == AccrualStatus.CANCELLED
