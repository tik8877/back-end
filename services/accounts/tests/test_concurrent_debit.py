import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from common.errors import ConflictError
from services.accounts.app.config import Settings
from services.accounts.app.models import Account
from services.accounts.app.service import AccountService, request_digest


@pytest.mark.asyncio
async def test_concurrent_debit_never_makes_negative_balance(session_factory):
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("Проверка блокировок выполняется на PostgreSQL")
    settings = Settings(database_url=os.environ["TEST_DATABASE_URL"])
    async with session_factory() as setup_session:
        service = AccountService(setup_session, settings)
        account = await service.create_account(uuid4(), "create-concurrent")
        await service.deposit(
            account.id,
            Decimal("100.00"),
            "deposit-concurrent",
            request_digest({"amount": "100.00"}),
        )
        account_id = account.id

    async def debit(number: int) -> bool:
        async with session_factory() as task_session:
            try:
                await AccountService(task_session, settings).withdraw(
                    account_id,
                    Decimal("20.00"),
                    f"withdraw-{number}",
                    request_digest({"amount": "20.00"}),
                )
                return True
            except ConflictError:
                return False

    results = await asyncio.gather(*(debit(number) for number in range(10)))

    async with session_factory() as check_session:
        account = await check_session.scalar(select(Account).where(Account.id == account_id))
    assert sum(results) == 5
    assert account.balance == Decimal("0.00")
    assert account.available_balance == Decimal("0.00")
