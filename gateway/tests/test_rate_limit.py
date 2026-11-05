from uuid import uuid4

import pytest

from gateway.app.core.rate_limit import check_rate_limit


class Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.key = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def incr(self, key):
        self.key = key

    def expire(self, key, seconds):
        return None

    async def execute(self):
        self.redis.count += 1
        return [self.redis.count, True]


class FakeRedis:
    def __init__(self):
        self.count = 0

    def pipeline(self, transaction=True):
        return Pipeline(self)


class BrokenRedis:
    def pipeline(self, transaction=True):
        raise ConnectionError()


@pytest.mark.asyncio
async def test_limit_is_shared_by_storage():
    redis = FakeRedis()
    user_id = uuid4()
    assert await check_rate_limit(redis, user_id, 2, 60) == (True, 1)
    assert await check_rate_limit(redis, user_id, 2, 60) == (True, 0)
    assert await check_rate_limit(redis, user_id, 2, 60) == (False, 0)


@pytest.mark.asyncio
async def test_storage_failure_does_not_block_request():
    assert await check_rate_limit(BrokenRedis(), uuid4(), 2, 60) == (True, 2)
