import time
from uuid import UUID

import structlog
from redis.asyncio import Redis


async def check_rate_limit(
    redis: Redis,
    user_id: UUID,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    now = int(time.time())
    window_start = now - now % window_seconds
    key = f"rl:{user_id}:{window_start}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds + 1)
            count, _ = await pipe.execute()
        used = int(count)
        return used <= limit, max(0, limit - used)
    except Exception as exc:
        structlog.get_logger().warning(
            "rate_limit_storage_unavailable",
            details={"error_type": type(exc).__name__},
        )
        return True, limit
