from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db import Base
from services.notification.app.config import Settings
from services.notification.app.consumer import process_event
from services.notification.app.models import Subscription
from services.notification.app.sender import DeliveryFailed


class Sender:
    def __init__(self):
        self.calls = 0

    async def send(self, *args):
        self.calls += 1


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    value = async_sessionmaker(engine, expire_on_commit=False)
    yield value
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_event_is_sent_once(factory):
    user_id = uuid4()
    async with factory() as session, session.begin():
        session.add(
            Subscription(
                user_id=user_id,
                event_type="transfer.completed",
                created_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
    payload = {
        "event_id": str(uuid4()),
        "user_id": str(user_id),
        "event_type": "transfer.completed",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    sender = Sender()
    await process_event(factory, sender, Settings(), payload)
    await process_event(factory, sender, Settings(), payload)
    assert sender.calls == 1


@pytest.mark.asyncio
async def test_event_before_unsubscribe_is_skipped(factory):
    user_id = uuid4()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(
            Subscription(
                user_id=user_id,
                event_type="account.closed",
                created_at=now - timedelta(days=1),
                unsubscribed_at=now,
            )
        )
    sender = Sender()
    result, _ = await process_event(
        factory,
        sender,
        Settings(),
        {
            "event_id": str(uuid4()),
            "user_id": str(user_id),
            "event_type": "account.closed",
            "timestamp": (now - timedelta(minutes=1)).isoformat(),
        },
    )
    assert result == "done"
    assert sender.calls == 0


@pytest.mark.asyncio
async def test_failed_delivery_waits_then_moves_to_manual_review(factory):
    user_id = uuid4()
    async with factory() as session, session.begin():
        session.add(
            Subscription(
                user_id=user_id,
                event_type="transfer.failed",
                created_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )

    class FailingSender:
        async def send(self, *args):
            raise DeliveryFailed("receiver_unavailable")

    payload = {
        "event_id": str(uuid4()),
        "user_id": str(user_id),
        "event_type": "transfer.failed",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    settings = Settings(max_delivery_attempts=2, delivery_delay_base_seconds=1)
    first = await process_event(factory, FailingSender(), settings, payload)
    second = await process_event(factory, FailingSender(), settings, payload)
    assert first == ("later", 1)
    assert second == ("manual", 2)


@pytest.mark.asyncio
async def test_event_without_subscription_is_skipped(factory):
    sender = Sender()
    result, _ = await process_event(
        factory,
        sender,
        Settings(),
        {
            "event_id": str(uuid4()),
            "user_id": str(uuid4()),
            "event_type": "account.created",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert result == "done"
    assert sender.calls == 0
