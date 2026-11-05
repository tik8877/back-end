from decimal import Decimal
from uuid import uuid4

import pytest

from services.antifraud.app.config import Settings
from services.antifraud.app.rules import DecisionService
from services.antifraud.app.schemas import CheckRequest


class Redis:
    def __init__(self, blocked=None):
        self.blocked = blocked
        self.count = 0

    async def sismember(self, key, value):
        return value == self.blocked

    async def incr(self, key):
        self.count += 1
        return self.count

    async def expire(self, key, ttl):
        return True


class Storage:
    def __init__(self, blocked=None):
        self.redis = Redis(blocked)
        self.value = None

    async def cached(self, transfer_id):
        return self.value

    async def acquire(self, transfer_id, owner):
        return True

    async def release(self, transfer_id, owner):
        return None

    async def save(self, transfer_id, decision):
        self.value = decision

    async def rules(self):
        return [{"id": "frequency", "type": "frequency", "limit": 2, "enabled": True, "shadow_mode": False}]


@pytest.mark.asyncio
async def test_blacklist_denies_receiver():
    receiver = uuid4()
    service = DecisionService(Storage(str(receiver)), Settings())
    result = await service.check(
        CheckRequest(
            transfer_id=uuid4(), sender_id=uuid4(), receiver_id=receiver, amount=Decimal("1")
        )
    )
    assert result.allowed is False
    assert result.reason_code == "115fz"


@pytest.mark.asyncio
async def test_repeated_transfer_does_not_increment_history():
    storage = Storage()
    service = DecisionService(storage, Settings())
    body = CheckRequest(
        transfer_id=uuid4(), sender_id=uuid4(), receiver_id=uuid4(), amount=Decimal("1")
    )
    first = await service.check(body)
    second = await service.check(body)
    assert first == second
    assert storage.redis.count == 1


@pytest.mark.asyncio
async def test_amount_rule_denies_and_observation_rule_does_not():
    storage = Storage()

    async def rules():
        return [
            {"id": "observe", "type": "frequency", "limit": 0, "enabled": True, "shadow_mode": True},
            {"id": "amount", "type": "amount", "limit": 10, "enabled": True, "shadow_mode": False},
        ]

    storage.rules = rules
    result = await DecisionService(storage, Settings()).check(
        CheckRequest(
            transfer_id=uuid4(), sender_id=uuid4(), receiver_id=uuid4(), amount=Decimal("11")
        )
    )
    assert result.allowed is False
    assert result.reason_code == "rule:amount"


@pytest.mark.asyncio
async def test_storage_failure_returns_configured_decision():
    class Broken(Storage):
        async def cached(self, transfer_id):
            raise ConnectionError()

    result = await DecisionService(Broken(), Settings(storage_failure_allow=False)).check(
        CheckRequest(
            transfer_id=uuid4(), sender_id=uuid4(), receiver_id=uuid4(), amount=Decimal("1")
        )
    )
    assert result.allowed is False
    assert result.reason_code == "storage_unavailable"
