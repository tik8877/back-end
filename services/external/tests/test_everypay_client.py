from datetime import UTC, datetime

import httpx
import pytest

from services.external.app.config import Settings
from services.external.app.everypay_client import EveryPayClient
from services.external.app.everypay_client import SourceUnavailable


@pytest.mark.asyncio
async def test_limited_source_is_called_again():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"items": [], "next_cursor": None, "total_pages": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = EveryPayClient(
            client,
            Settings(
                external_wait_base_seconds=0.001,
                external_wait_max_seconds=0.001,
                external_max_attempts=2,
            ),
        )
        page = await source.fetch_page(datetime.now(UTC), datetime.now(UTC), None)
    assert page.total_pages == 1
    assert calls == 2


@pytest.mark.asyncio
async def test_source_error_exhausts_attempts():
    async def handler(request):
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = EveryPayClient(
            client,
            Settings(
                external_wait_base_seconds=0,
                external_wait_max_seconds=0,
                external_max_attempts=2,
            ),
        )
        with pytest.raises(SourceUnavailable):
            await source.fetch_page(datetime.now(UTC), datetime.now(UTC), None)
