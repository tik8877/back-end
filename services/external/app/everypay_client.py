import asyncio
from dataclasses import dataclass
from datetime import datetime

import httpx

from services.external.app.config import Settings


class SourceUnavailable(Exception):
    pass


@dataclass(slots=True)
class SourcePage:
    items: list[dict]
    next_cursor: str | None
    total_pages: int | None


class EveryPayClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def fetch_page(
        self,
        date_from: datetime,
        date_to: datetime,
        cursor: str | None,
    ) -> SourcePage:
        delay = self.settings.external_wait_base_seconds
        for attempt in range(self.settings.external_max_attempts):
            try:
                response = await self.client.get(
                    f"{self.settings.everypay_base_url}/transactions",
                    params={
                        "from": date_from.isoformat(),
                        "to": date_to.isoformat(),
                        "cursor": cursor,
                    },
                    headers={"X-Api-Key": self.settings.everypay_api_key},
                    timeout=self.settings.external_timeout_seconds,
                )
                if response.status_code == 429:
                    wait = float(response.headers.get("Retry-After", delay))
                    await asyncio.sleep(min(wait, self.settings.external_wait_max_seconds))
                    continue
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError("source error", request=response.request, response=response)
                response.raise_for_status()
                body = response.json()
                return SourcePage(
                    items=list(body.get("items", [])),
                    next_cursor=body.get("next_cursor"),
                    total_pages=body.get("total_pages"),
                )
            except asyncio.CancelledError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError):
                if attempt + 1 >= self.settings.external_max_attempts:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.settings.external_wait_max_seconds)
        raise SourceUnavailable()
