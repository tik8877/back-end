import hashlib
import json
import time
from decimal import Decimal
from uuid import UUID, uuid4

import structlog
from prometheus_client import Counter

from services.antifraud.app.config import Settings
from services.antifraud.app.schemas import CheckRequest, CheckResponse
from services.antifraud.app.storage import DecisionStorage


SHADOW_MATCHES = Counter(
    "antifraud_observation_rule_matches_total",
    "Срабатывания правил в режиме наблюдения",
    ("rule_id",),
)


class DecisionService:
    def __init__(self, storage: DecisionStorage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings

    async def check(self, body: CheckRequest) -> CheckResponse:
        try:
            if cached := await self.storage.cached(body.transfer_id):
                return cached
            owner = str(uuid4())
            acquired = await self.storage.acquire(body.transfer_id, owner)
            if not acquired:
                if cached := await self.storage.cached(body.transfer_id):
                    return cached
                return CheckResponse(
                    allowed=self.settings.storage_failure_allow,
                    reason_code="decision_in_progress",
                    rules_version="unavailable",
                )
            try:
                if cached := await self.storage.cached(body.transfer_id):
                    return cached
                decision = await self._calculate(body)
                await self.storage.save(body.transfer_id, decision)
                structlog.get_logger().info(
                    "antifraud_decision",
                    details={
                        "transfer_id": str(body.transfer_id),
                        "allowed": decision.allowed,
                        "reason_code": decision.reason_code,
                        "rules_version": decision.rules_version,
                    },
                )
                return decision
            finally:
                await self.storage.release(body.transfer_id, owner)
        except Exception as exc:
            structlog.get_logger().warning(
                "antifraud_storage_failure",
                details={"error_type": type(exc).__name__},
            )
            return CheckResponse(
                allowed=self.settings.storage_failure_allow,
                reason_code="storage_unavailable",
                rules_version="unavailable",
            )

    async def _calculate(self, body: CheckRequest) -> CheckResponse:
        rules = await self.storage.rules()
        version = hashlib.sha256(
            json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if await self.storage.redis.sismember("blacklist:115fz", str(body.receiver_id)):
            return CheckResponse(allowed=False, reason_code="115fz", rules_version=version)

        window = int(time.time()) // self.settings.history_window_seconds
        history_key = f"history:{body.sender_id}:{body.receiver_id}:{window}"
        count = await self.storage.redis.incr(history_key)
        if count == 1:
            await self.storage.redis.expire(
                history_key, self.settings.history_window_seconds + 1
            )

        denial: str | None = None
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            matched = False
            if rule.get("type") == "frequency":
                matched = count > int(rule["limit"])
            elif rule.get("type") == "amount":
                matched = body.amount > Decimal(str(rule["limit"]))
            if matched and rule.get("shadow_mode", False):
                SHADOW_MATCHES.labels(str(rule["id"])).inc()
            elif matched:
                denial = f"rule:{rule['id']}"
                break
        return CheckResponse(
            allowed=denial is None,
            reason_code=denial or "allowed",
            rules_version=version,
        )
