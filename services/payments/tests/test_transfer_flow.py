from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db import Base
from services.payments.app.clients import (
    AntifraudDecision,
    DependencyRejected,
    DependencyUnavailable,
)
from services.payments.app.config import Settings
from services.payments.app.models import TransferStatus
from services.payments.app.service import TransferCoordinator, request_digest
from common.errors import BadRequestError


class FraudUnavailable:
    async def check(self, *args):
        raise DependencyUnavailable()


class FraudAllowed:
    async def check(self, *args):
        return AntifraudDecision(True, "allowed", "v1")


class Accounts:
    def __init__(self, receiver_id: UUID, fail_credit: bool = False):
        self.receiver_id = receiver_id
        self.fail_credit = fail_credit
        self.returned = False

    async def reserve(self, account_id, amount, key):
        return {"reservation_id": str(uuid4())}

    async def confirm(self, reservation_id, key):
        return {"status": "confirmed"}

    async def cancel(self, reservation_id, key):
        return {"status": "cancelled"}

    async def deposit(self, account_id, amount, key):
        if account_id == self.receiver_id and self.fail_credit:
            raise DependencyRejected("CREDIT_REJECTED")
        self.returned = key.endswith(":return")
        return {"status": "completed"}


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    value = async_sessionmaker(engine, expire_on_commit=False)
    yield value
    await engine.dispose()


@pytest.mark.asyncio
async def test_unavailable_antifraud_allows_small_transfer(factory):
    sender, receiver = uuid4(), uuid4()
    coordinator = TransferCoordinator(
        factory,
        FraudUnavailable(),
        Accounts(receiver),
        Settings(database_url="sqlite+aiosqlite:///:memory:", safe_limit=1000),
    )
    transfer = await coordinator.create_transfer(
        uuid4(), sender, receiver, Decimal("100.00"), "key-1", request_digest({"amount": "100.00"})
    )
    assert transfer.status == TransferStatus.COMPLETED
    assert transfer.antifraud_reason == "antifraud_unavailable_safe_limit"


@pytest.mark.asyncio
async def test_unavailable_antifraud_rejects_large_transfer(factory):
    sender, receiver = uuid4(), uuid4()
    coordinator = TransferCoordinator(
        factory,
        FraudUnavailable(),
        Accounts(receiver),
        Settings(database_url="sqlite+aiosqlite:///:memory:", safe_limit=1000),
    )
    transfer = await coordinator.create_transfer(
        uuid4(), sender, receiver, Decimal("1000.00"), "key-2", request_digest({"amount": "1000.00"})
    )
    assert transfer.status == TransferStatus.FAILED
    assert transfer.error_code == "ANTIFRAUD_UNAVAILABLE"


@pytest.mark.asyncio
async def test_credit_failure_returns_money(factory):
    sender, receiver = uuid4(), uuid4()
    accounts = Accounts(receiver, fail_credit=True)
    coordinator = TransferCoordinator(
        factory,
        FraudAllowed(),
        accounts,
        Settings(database_url="sqlite+aiosqlite:///:memory:"),
    )
    transfer = await coordinator.create_transfer(
        uuid4(), sender, receiver, Decimal("10.00"), "key-3", request_digest({"amount": "10.00"})
    )
    assert transfer.status == TransferStatus.COMPENSATED
    assert accounts.returned is True


@pytest.mark.asyncio
async def test_same_account_and_changed_repeat_are_rejected(factory):
    account_id = uuid4()
    coordinator = TransferCoordinator(
        factory,
        FraudAllowed(),
        Accounts(uuid4()),
        Settings(database_url="sqlite+aiosqlite:///:memory:"),
    )
    with pytest.raises(BadRequestError) as same:
        await coordinator.create_transfer(
            uuid4(), account_id, account_id, Decimal("1"), "same", "x" * 64
        )
    assert same.value.error_code == "SAME_ACCOUNT"

    sender, receiver = uuid4(), uuid4()
    digest = request_digest({"amount": "1"})
    first = await coordinator.create_transfer(
        uuid4(), sender, receiver, Decimal("1"), "repeat", digest
    )
    repeated = await coordinator.create_transfer(
        first.user_id, sender, receiver, Decimal("1"), "repeat", digest
    )
    assert first.id == repeated.id
    with pytest.raises(BadRequestError) as changed:
        await coordinator.create_transfer(
            first.user_id,
            sender,
            receiver,
            Decimal("2"),
            "repeat",
            request_digest({"amount": "2"}),
        )
    assert changed.value.error_code == "IDEMPOTENCY_KEY_REUSE"
