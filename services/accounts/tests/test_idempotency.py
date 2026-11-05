from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from common.errors import BadRequestError
from services.accounts.app.config import Settings
from services.accounts.app.models import Account
from services.accounts.app.service import AccountService, request_digest


@pytest.mark.asyncio
async def test_deposit_is_repeated_without_balance_change(session):
    service = AccountService(session, Settings(database_url="sqlite+aiosqlite:///:memory:"))
    account = await service.create_account(uuid4(), "create-1")
    digest = request_digest({"amount": "25.00"})

    first = await service.deposit(account.id, Decimal("25.00"), "deposit-1", digest)
    second = await service.deposit(account.id, Decimal("25.00"), "deposit-1", digest)

    refreshed = await session.scalar(select(Account).where(Account.id == account.id))
    assert first.id == second.id
    assert first.response_body == second.response_body
    assert refreshed.balance == Decimal("25.00")
    assert refreshed.available_balance == Decimal("25.00")


@pytest.mark.asyncio
async def test_same_key_with_other_body_is_rejected(session):
    service = AccountService(session, Settings(database_url="sqlite+aiosqlite:///:memory:"))
    account = await service.create_account(uuid4(), "create-2")
    await service.deposit(
        account.id,
        Decimal("10.00"),
        "deposit-2",
        request_digest({"amount": "10.00"}),
    )

    with pytest.raises(BadRequestError) as error:
        await service.deposit(
            account.id,
            Decimal("11.00"),
            "deposit-2",
            request_digest({"amount": "11.00"}),
        )

    assert error.value.error_code == "IDEMPOTENCY_KEY_REUSE"
