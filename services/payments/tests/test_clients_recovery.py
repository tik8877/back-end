from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db import Base
from common.time import utc_now
from services.payments.app.clients import (
    AccountsClient,
    AntifraudClient,
    DependencyRejected,
    DependencyUnavailable,
)
from services.payments.app.models import Transfer, TransferStatus
from services.payments.app.recovery_worker import recover_stale_transfers


@pytest.mark.asyncio
async def test_accounts_client_checks_result_after_timeout():
    async def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(
            200,
            json={"response_body": {"reservation_id": str(uuid4())}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await AccountsClient(http, "http://accounts", 0.1, 2, 0).reserve(
            uuid4(), Decimal("10.00"), "key"
        )
    assert "reservation_id" in result


@pytest.mark.asyncio
async def test_antifraud_client_reports_unavailable_on_server_error():
    async def handler(request):
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AntifraudClient(http, "http://antifraud", 0.1)
        with pytest.raises(DependencyUnavailable):
            await client.check(uuid4(), uuid4(), uuid4(), Decimal("1"))


@pytest.mark.asyncio
async def test_clients_parse_successful_responses():
    reservation_id = uuid4()

    async def handler(request):
        if request.url.path == "/check":
            return httpx.Response(
                200,
                json={"allowed": True, "reason_code": "allowed", "rules_version": "v1"},
            )
        if request.url.path.endswith("/reserve"):
            return httpx.Response(200, json={"reservation_id": str(reservation_id)})
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(200, json={"status": "completed"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        fraud = await AntifraudClient(http, "http://antifraud", 0.1).check(
            uuid4(), uuid4(), uuid4(), Decimal("1")
        )
        accounts = AccountsClient(http, "http://accounts", 0.1, 2, 0)
        reserved = await accounts.reserve(uuid4(), Decimal("1"), "reserve")
        await accounts.confirm(reservation_id, "confirm")
        await accounts.cancel(reservation_id, "cancel")
        await accounts.deposit(uuid4(), Decimal("1"), "deposit")
        missing = await accounts.get_operation_by_key("missing")
    assert fraud.allowed is True
    assert reserved["reservation_id"] == str(reservation_id)
    assert missing is None


@pytest.mark.asyncio
async def test_accounts_client_surfaces_business_rejection():
    async def handler(request):
        return httpx.Response(409, json={"error_code": "INSUFFICIENT_FUNDS"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(DependencyRejected) as error:
            await AccountsClient(http, "http://accounts", 0.1, 2, 0).reserve(
                uuid4(), Decimal("10"), "key"
            )
    assert error.value.code == "INSUFFICIENT_FUNDS"


@pytest.mark.asyncio
async def test_accounts_client_keeps_unknown_result_unresolved():
    async def handler(request):
        if request.method == "POST":
            return httpx.Response(503)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(DependencyUnavailable):
            await AccountsClient(http, "http://accounts", 0.1, 2, 0).reserve(
                uuid4(), Decimal("10"), "unknown"
            )


@pytest.mark.asyncio
async def test_recovery_selects_stale_transfer():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    transfer_id = uuid4()
    async with factory() as session, session.begin():
        session.add(
            Transfer(
                id=transfer_id,
                user_id=uuid4(),
                sender_account_id=uuid4(),
                receiver_account_id=uuid4(),
                amount=Decimal("1"),
                status=TransferStatus.PROCESSING,
                idempotency_key="stale",
                request_hash="x" * 64,
                updated_at=utc_now() - timedelta(minutes=5),
            )
        )

    class Coordinator:
        def __init__(self):
            self.ids = []

        async def process_transfer(self, value):
            self.ids.append(value)

    coordinator = Coordinator()
    assert await recover_stale_transfers(factory, coordinator, 30, 10) == 1
    assert coordinator.ids == [transfer_id]
    await engine.dispose()
