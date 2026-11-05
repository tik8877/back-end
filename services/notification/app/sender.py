import asyncio

import httpx


class DeliveryFailed(Exception):
    def __init__(self, reason: str, delay_seconds: int | None = None) -> None:
        self.reason = reason
        self.delay_seconds = delay_seconds
        super().__init__(reason)


class TelegramSender:
    def __init__(self, client: httpx.AsyncClient, url: str, timeout: float) -> None:
        self.client = client
        self.url = url
        self.timeout = timeout

    async def send(self, event_id: str, user_id: str, event_type: str) -> None:
        try:
            response = await self.client.post(
                f"{self.url}/send",
                json={"event_id": event_id, "user_id": user_id, "event_type": event_type},
                headers={"Idempotency-Key": event_id},
                timeout=self.timeout,
            )
            if response.status_code == 429:
                delay = int(response.headers.get("Retry-After", "0") or 0)
                raise DeliveryFailed("limited", delay or None)
            if response.status_code >= 500:
                raise DeliveryFailed("receiver_unavailable")
            if response.status_code >= 400:
                raise DeliveryFailed("receiver_rejected")
        except asyncio.CancelledError:
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise DeliveryFailed("connection_failed") from exc
