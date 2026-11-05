import asyncio
import json
from uuid import UUID

from redis.asyncio import Redis

from services.antifraud.app.config import Settings
from services.antifraud.app.schemas import CheckResponse


class DecisionStorage:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    async def cached(self, transfer_id: UUID) -> CheckResponse | None:
        value = await self.redis.get(f"decision:{transfer_id}")
        return CheckResponse.model_validate_json(value) if value else None

    async def acquire(self, transfer_id: UUID, owner: str) -> bool:
        key = f"decision_lock:{transfer_id}"
        for _ in range(self.settings.decision_lock_wait_attempts):
            if await self.redis.set(
                key,
                owner,
                nx=True,
                ex=self.settings.decision_lock_ttl_seconds,
            ):
                return True
            if await self.redis.exists(f"decision:{transfer_id}"):
                return False
            await asyncio.sleep(self.settings.decision_lock_wait_seconds)
        return False

    async def release(self, transfer_id: UUID, owner: str) -> None:
        key = f"decision_lock:{transfer_id}"
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
          return redis.call('del', KEYS[1])
        end
        return 0
        """
        await self.redis.eval(script, 1, key, owner)

    async def save(self, transfer_id: UUID, decision: CheckResponse) -> None:
        await self.redis.set(
            f"decision:{transfer_id}",
            decision.model_dump_json(),
            ex=self.settings.decision_ttl_seconds,
        )

    async def rules(self) -> list[dict]:
        rules: list[dict] = []
        async for key in self.redis.scan_iter(match="rule:*"):
            value = await self.redis.get(key)
            if value:
                rule = json.loads(value)
                rule["id"] = str(key).split(":", 1)[1]
                rules.append(rule)
        if not rules:
            rules = [
                {
                    "id": "default_frequency",
                    "type": "frequency",
                    "limit": self.settings.default_frequency_limit,
                    "enabled": True,
                    "shadow_mode": False,
                },
                {
                    "id": "default_amount",
                    "type": "amount",
                    "limit": self.settings.default_amount_limit,
                    "enabled": True,
                    "shadow_mode": False,
                },
            ]
        return sorted(rules, key=lambda item: item["id"])
