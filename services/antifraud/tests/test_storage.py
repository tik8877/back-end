import json
from uuid import uuid4

import pytest

from services.antifraud.app.config import Settings
from services.antifraud.app.schemas import CheckResponse
from services.antifraud.app.storage import DecisionStorage


class Redis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def exists(self, key):
        return key in self.values

    async def eval(self, script, count, key, owner):
        if self.values.get(key) == owner:
            del self.values[key]
            return 1
        return 0

    async def scan_iter(self, match):
        for key in list(self.values):
            if key.startswith("rule:"):
                yield key


@pytest.mark.asyncio
async def test_decision_storage_cache_lock_and_rules():
    redis = Redis()
    redis.values["rule:amount"] = json.dumps({"type": "amount", "limit": 10})
    storage = DecisionStorage(redis, Settings(decision_lock_wait_seconds=0))
    transfer_id = uuid4()
    assert await storage.cached(transfer_id) is None
    assert await storage.acquire(transfer_id, "owner") is True
    await storage.release(transfer_id, "owner")
    decision = CheckResponse(allowed=True, reason_code="allowed", rules_version="v1")
    await storage.save(transfer_id, decision)
    assert await storage.cached(transfer_id) == decision
    assert (await storage.rules())[0]["id"] == "amount"
