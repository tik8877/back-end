from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from common.errors import ConflictError
from common.time import utc_now
from services.accounts.app.config import Settings
from services.accounts.app.models import Account, AccountStatus, Reservation, ReservationStatus
from services.accounts.app.service import AccountService


@pytest.mark.asyncio
async def test_close_requires_zero_balance_no_reserve_and_idle_period(session):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        close_account_min_idle_days=30,
    )
    service = AccountService(session, settings)
    account = Account(
        user_id=uuid4(),
        creation_key="close-setup",
        balance=Decimal("1.00"),
        available_balance=Decimal("1.00"),
        status=AccountStatus.ACTIVE,
        last_operation_at=utc_now() - timedelta(days=31),
    )
    session.add(account)
    await session.commit()
    account_id = account.id

    with pytest.raises(ConflictError) as non_zero:
        await service.close_account(account_id, "close-1")
    assert non_zero.value.error_code == "NON_ZERO_BALANCE"

    account = await session.get(Account, account_id)
    account.balance = Decimal("0.00")
    account.available_balance = Decimal("0.00")
    reservation = Reservation(
        account_id=account_id,
        amount=Decimal("1.00"),
        expires_at=utc_now() + timedelta(days=1),
        status=ReservationStatus.ACTIVE,
    )
    session.add(reservation)
    await session.commit()
    reservation_id = reservation.id
    with pytest.raises(ConflictError) as active:
        await service.close_account(account_id, "close-2")
    assert active.value.error_code == "ACTIVE_RESERVATIONS"

    account = await session.get(Account, account_id)
    reservation = await session.get(Reservation, reservation_id)
    reservation.status = ReservationStatus.CANCELLED
    account.last_operation_at = utc_now() - timedelta(days=10)
    await session.commit()
    with pytest.raises(ConflictError) as recent:
        await service.close_account(account_id, "close-3")
    assert recent.value.error_code == "ACCOUNT_NOT_IDLE"

    account = await session.get(Account, account_id)
    account.last_operation_at = utc_now() - timedelta(days=31)
    await session.commit()
    first = await service.close_account(account_id, "close-4")
    second = await service.close_account(account_id, "close-4")
    assert first.id == second.id
    assert account.status == AccountStatus.CLOSED
