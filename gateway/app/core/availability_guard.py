import asyncio
import time

import httpx
import structlog
from redis.asyncio import Redis

from gateway.app.config import Settings


class ServiceAvailabilityGuard:
    def __init__(self, redis: Redis, settings: Settings, client: httpx.AsyncClient) -> None:
        self.redis = redis
        self.settings = settings
        self.client = client

    async def should_reject_fast(self, service_name: str) -> bool:
        try:
            value = await self.redis.get(f"svc_unavailable_until:{service_name}")
            return value is not None and float(value) > time.time()
        except Exception as exc:
            structlog.get_logger().warning(
                "service_state_storage_unavailable",
                details={"service_name": service_name, "error_type": type(exc).__name__},
            )
            return False

    async def record_success(self, service_name: str) -> None:
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.set(f"svc_state:{service_name}", "ok")
                pipe.delete(f"svc_fail_count:{service_name}")
                pipe.delete(f"svc_unavailable_until:{service_name}")
                await pipe.execute()
        except Exception:
            return

    async def record_failure(self, service_name: str) -> None:
        try:
            count = int(await self.redis.incr(f"svc_fail_count:{service_name}"))
            if count >= self.settings.service_unavailable_threshold:
                unavailable_until = time.time() + self.settings.service_unavailable_cooldown_seconds
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.set(f"svc_state:{service_name}", "unavailable")
                    pipe.set(
                        f"svc_unavailable_until:{service_name}",
                        unavailable_until,
                        ex=self.settings.service_unavailable_cooldown_seconds,
                    )
                    await pipe.execute()
        except Exception:
            return

    async def probe_worker(self) -> None:
        while True:
            await asyncio.sleep(self.settings.service_unavailable_probe_interval_seconds)
            for name, base_url in self.settings.service_urls.items():
                if not await self.should_reject_fast(name):
                    continue
                try:
                    response = await self.client.get(f"{base_url}/health/live")
                    if response.status_code < 500:
                        await self.record_success(name)
                except asyncio.CancelledError:
                    raise
                except (httpx.HTTPError, RuntimeError):
                    continue
