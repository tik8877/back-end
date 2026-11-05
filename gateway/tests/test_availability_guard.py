import time

import pytest

from gateway.app.config import Settings
from gateway.app.core.availability_guard import ServiceAvailabilityGuard


class Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.actions = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def set(self, key, value, **kwargs):
        self.actions.append(("set", key, str(value)))

    def delete(self, key):
        self.actions.append(("delete", key, None))

    async def execute(self):
        for action, key, value in self.actions:
            if action == "set":
                self.redis.values[key] = value
            else:
                self.redis.values.pop(key, None)
        return [True] * len(self.actions)


class Redis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def incr(self, key):
        self.values[key] = str(int(self.values.get(key, 0)) + 1)
        return int(self.values[key])

    def pipeline(self, transaction=True):
        return Pipeline(self)


@pytest.mark.asyncio
async def test_failure_temporarily_excludes_service_and_success_resets():
    redis = Redis()
    guard = ServiceAvailabilityGuard(
        redis,
        Settings(service_unavailable_threshold=2, service_unavailable_cooldown_seconds=30),
        object(),
    )
    assert await guard.should_reject_fast("accounts") is False
    await guard.record_failure("accounts")
    assert await guard.should_reject_fast("accounts") is False
    await guard.record_failure("accounts")
    assert await guard.should_reject_fast("accounts") is True
    await guard.record_success("accounts")
    assert await guard.should_reject_fast("accounts") is False


@pytest.mark.asyncio
async def test_expired_exclusion_does_not_reject():
    redis = Redis()
    redis.values["svc_unavailable_until:accounts"] = str(time.time() - 1)
    guard = ServiceAvailabilityGuard(redis, Settings(), object())
    assert await guard.should_reject_fast("accounts") is False
