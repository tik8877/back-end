from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from common.time import utc_now
from services.accounts.app.closing_worker import close_idle_accounts
from services.accounts.app.config import Settings
from services.accounts.app.models import Account, AccountStatus, Reservation, ReservationStatus
from services.accounts.app.reservations_worker import expire_reservations
from services.accounts.app.service import AccountService, request_digest


@pytest.mark.asyncio
async def test_reserve_confirm_cancel_and_repeat(session):
    service = AccountService(session, Settings(database_url="sqlite+aiosqlite:///:memory:"))
    account = await service.create_account(uuid4(), "create-reserve")
    await service.deposit(
        account.id,
        Decimal("100.00"),
        "deposit-reserve",
        request_digest({"amount": "100.00"}),
    )
    digest = request_digest({"amount": "30.00"})
    reservation = await service.reserve(account.id, Decimal("30.00"), "reserve-1", digest)
    repeated = await service.reserve(account.id, Decimal("30.00"), "reserve-1", digest)
    assert repeated.id == reservation.id
    await service.finish_reservation(reservation.id, "confirm-1", True)
    confirmed = await service.finish_reservation(reservation.id, "confirm-1", True)
    assert confirmed.status == ReservationStatus.CONFIRMED

    second = await service.reserve(
        account.id,
        Decimal("20.00"),
        "reserve-2",
        request_digest({"amount": "20.00"}),
    )
    await service.finish_reservation(second.id, "cancel-2", False)
    refreshed = await session.get(Account, account.id)
    assert refreshed.balance == Decimal("70.00")
    assert refreshed.available_balance == Decimal("70.00")


@pytest.mark.asyncio
async def test_expiry_releases_available_balance(session_factory):
    account_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            Account(
                id=account_id,
                user_id=uuid4(),
                creation_key="expiry",
                balance=Decimal("100.00"),
                available_balance=Decimal("70.00"),
                status=AccountStatus.ACTIVE,
            )
        )
        reservation = Reservation(
            account_id=account_id,
            amount=Decimal("30.00"),
            expires_at=utc_now() - timedelta(seconds=1),
        )
        session.add(reservation)
    assert await expire_reservations(session_factory, 100) == 1
    async with session_factory() as session:
        account = await session.get(Account, account_id)
        saved = await session.scalar(select(Reservation).where(Reservation.account_id == account_id))
    assert account.available_balance == Decimal("100.00")
    assert saved.status == ReservationStatus.EXPIRED


@pytest.mark.asyncio
async def test_idle_account_worker_closes_once(session_factory):
    account_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            Account(
                id=account_id,
                user_id=uuid4(),
                creation_key="idle",
                balance=Decimal("0.00"),
                available_balance=Decimal("0.00"),
                status=AccountStatus.ACTIVE,
                last_operation_at=utc_now() - timedelta(days=31),
            )
        )
    assert await close_idle_accounts(session_factory, 30, 100) == 1
    assert await close_idle_accounts(session_factory, 30, 100) == 0
    async with session_factory() as session:
        account = await session.get(Account, account_id)
    assert account.status == AccountStatus.CLOSED
