import asyncio
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import httpx


class DependencyUnavailable(Exception):
    pass


class DependencyRejected(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(slots=True)
class AntifraudDecision:
    allowed: bool
    reason_code: str
    rules_version: str | None = None


class AntifraudClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str, timeout: float) -> None:
        self.client = client
        self.base_url = base_url
        self.timeout = timeout

    async def check(
        self,
        transfer_id: UUID,
        sender_id: UUID,
        receiver_id: UUID,
        amount: Decimal,
    ) -> AntifraudDecision:
        try:
            response = await self.client.post(
                f"{self.base_url}/check",
                json={
                    "transfer_id": str(transfer_id),
                    "sender_id": str(sender_id),
                    "receiver_id": str(receiver_id),
                    "amount": str(amount),
                },
                headers={"Idempotency-Key": str(transfer_id)},
                timeout=self.timeout,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise DependencyUnavailable("antifraud")
            response.raise_for_status()
            data = response.json()
            return AntifraudDecision(
                allowed=bool(data["allowed"]),
                reason_code=str(data["reason_code"]),
                rules_version=data.get("rules_version"),
            )
        except asyncio.CancelledError:
            raise
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            raise DependencyUnavailable("antifraud") from exc


class AccountsClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        timeout: float,
        status_check_attempts: int,
        status_check_pause_seconds: float,
    ) -> None:
        self.client = client
        self.base_url = base_url
        self.timeout = timeout
        self.status_check_attempts = status_check_attempts
        self.status_check_pause_seconds = status_check_pause_seconds

    async def _post(self, path: str, key: str, body: dict | None = None) -> dict:
        try:
            response = await self.client.post(
                f"{self.base_url}{path}",
                json=body,
                headers={"Idempotency-Key": key},
                timeout=self.timeout,
            )
            if response.status_code >= 500:
                raise DependencyUnavailable("accounts")
            if response.status_code >= 400:
                code = response.json().get("error_code", "ACCOUNTS_REJECTED")
                raise DependencyRejected(code)
            return response.json()
        except asyncio.CancelledError:
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise DependencyUnavailable("accounts") from exc

    async def get_operation_by_key(self, key: str) -> dict | None:
        for attempt in range(self.status_check_attempts):
            try:
                response = await self.client.get(
                    f"{self.base_url}/accounts/operations/by-key",
                    params={"idempotency_key": key},
                    timeout=self.timeout,
                )
                if response.status_code == 404:
                    return None
                if response.status_code >= 500:
                    raise DependencyUnavailable("accounts")
                response.raise_for_status()
                return response.json()
            except asyncio.CancelledError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt + 1 >= self.status_check_attempts:
                    raise DependencyUnavailable("accounts")
                await asyncio.sleep(self.status_check_pause_seconds)
        return None

    async def reserve(self, account_id: UUID, amount: Decimal, key: str) -> dict:
        try:
            return await self._post(
                f"/accounts/{account_id}/reserve", key, {"amount": str(amount)}
            )
        except DependencyUnavailable:
            known = await self.get_operation_by_key(key)
            if known and known.get("response_body"):
                return known["response_body"]
            raise

    async def confirm(self, reservation_id: UUID, key: str) -> dict:
        return await self._post(
            f"/accounts/reservations/{reservation_id}/confirm", key
        )

    async def cancel(self, reservation_id: UUID, key: str) -> dict:
        return await self._post(
            f"/accounts/reservations/{reservation_id}/cancel", key
        )

    async def deposit(self, account_id: UUID, amount: Decimal, key: str) -> dict:
        try:
            return await self._post(
                f"/accounts/{account_id}/deposit", key, {"amount": str(amount)}
            )
        except DependencyUnavailable:
            known = await self.get_operation_by_key(key)
            if known:
                return known
            raise
