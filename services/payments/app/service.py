import hashlib
import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.errors import BadRequestError, ConflictError, NotFoundError
from common.events import new_event
from common.observability import BUSINESS_OPERATIONS
from common.time import utc_now
from services.payments.app.clients import (
    AccountsClient,
    AntifraudClient,
    DependencyRejected,
    DependencyUnavailable,
)
from services.payments.app.config import Settings
from services.payments.app.models import Transfer, TransferStatus


def request_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class TransferCoordinator:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        antifraud: AntifraudClient,
        accounts: AccountsClient,
        settings: Settings,
    ) -> None:
        self.factory = factory
        self.antifraud = antifraud
        self.accounts = accounts
        self.settings = settings

    async def create_transfer(
        self,
        user_id: UUID,
        sender_id: UUID,
        receiver_id: UUID,
        amount: Decimal,
        key: str,
        digest: str,
    ) -> Transfer:
        if sender_id == receiver_id:
            raise BadRequestError("SAME_ACCOUNT", "Нельзя переводить на тот же счёт")
        async with self.factory() as session, session.begin():
            existing = await session.scalar(
                select(Transfer).where(Transfer.idempotency_key == key).with_for_update()
            )
            if existing:
                if existing.request_hash != digest:
                    raise BadRequestError(
                        "IDEMPOTENCY_KEY_REUSE", "Ключ уже использован для другого запроса"
                    )
                return existing
            transfer = Transfer(
                user_id=user_id,
                sender_account_id=sender_id,
                receiver_account_id=receiver_id,
                amount=amount,
                idempotency_key=key,
                request_hash=digest,
            )
            session.add(transfer)
            await session.flush()
            transfer_id = transfer.id
        await self.process_transfer(transfer_id)
        async with self.factory() as session:
            result = await session.get(Transfer, transfer_id)
            if not result:
                raise NotFoundError("TRANSFER_NOT_FOUND", "Перевод не найден")
            return result

    async def _set_failed(self, transfer_id: UUID, code: str) -> None:
        async with self.factory() as session, session.begin():
            transfer = await session.scalar(
                select(Transfer).where(Transfer.id == transfer_id).with_for_update()
            )
            if transfer and transfer.status not in {
                TransferStatus.COMPLETED,
                TransferStatus.COMPENSATED,
            }:
                transfer.status = TransferStatus.FAILED
                transfer.error_code = code
                transfer.completed_at = utc_now()
                session.add(
                    new_event(
                        "transfer.failed",
                        {"transfer_id": str(transfer.id), "error_code": code},
                    )
                )
        BUSINESS_OPERATIONS.labels(self.settings.service_name, "transfer", "failed").inc()

    async def process_transfer(self, transfer_id: UUID) -> None:
        async with self.factory() as session, session.begin():
            transfer = await session.scalar(
                select(Transfer).where(Transfer.id == transfer_id).with_for_update()
            )
            if not transfer or transfer.status not in {
                TransferStatus.PENDING,
                TransferStatus.PROCESSING,
            }:
                return
            transfer.status = TransferStatus.PROCESSING
            sender_id = transfer.sender_account_id
            receiver_id = transfer.receiver_account_id
            amount = transfer.amount
            reservation_id = transfer.reservation_id

        if reservation_id is None:
            try:
                decision = await self.antifraud.check(
                    transfer_id, sender_id, receiver_id, amount
                )
            except DependencyUnavailable:
                if amount < Decimal(self.settings.safe_limit):
                    allowed, reason = True, "antifraud_unavailable_safe_limit"
                else:
                    await self._set_failed(transfer_id, "ANTIFRAUD_UNAVAILABLE")
                    return
            else:
                allowed, reason = decision.allowed, decision.reason_code
            async with self.factory() as session, session.begin():
                transfer = await session.scalar(
                    select(Transfer).where(Transfer.id == transfer_id).with_for_update()
                )
                if not transfer:
                    return
                transfer.antifraud_decision = "allowed" if allowed else "denied"
                transfer.antifraud_reason = reason
            if not allowed:
                await self._set_failed(transfer_id, "ANTIFRAUD_DENIED")
                return
            try:
                reserved = await self.accounts.reserve(
                    sender_id, amount, str(transfer_id)
                )
                reservation_id = UUID(str(reserved["reservation_id"]))
            except DependencyRejected as exc:
                await self._set_failed(transfer_id, exc.code)
                return
            except DependencyUnavailable:
                return
            async with self.factory() as session, session.begin():
                transfer = await session.scalar(
                    select(Transfer).where(Transfer.id == transfer_id).with_for_update()
                )
                if transfer:
                    transfer.reservation_id = reservation_id

        try:
            await self.accounts.confirm(reservation_id, f"{transfer_id}:confirm")
        except DependencyUnavailable:
            return
        except DependencyRejected:
            try:
                await self.accounts.cancel(reservation_id, f"{transfer_id}:cancel")
            except DependencyUnavailable:
                return
            await self._set_compensated(transfer_id, "CONFIRM_FAILED")
            return

        try:
            await self.accounts.deposit(
                receiver_id, amount, f"{transfer_id}:credit"
            )
        except DependencyUnavailable:
            return
        except DependencyRejected:
            try:
                await self.accounts.deposit(
                    sender_id, amount, f"{transfer_id}:return"
                )
            except DependencyUnavailable:
                return
            await self._set_compensated(transfer_id, "CREDIT_FAILED")
            return

        async with self.factory() as session, session.begin():
            transfer = await session.scalar(
                select(Transfer).where(Transfer.id == transfer_id).with_for_update()
            )
            if transfer and transfer.status == TransferStatus.PROCESSING:
                transfer.status = TransferStatus.COMPLETED
                transfer.completed_at = utc_now()
                session.add(
                    new_event(
                        "transfer.completed",
                        {
                            "transfer_id": str(transfer.id),
                            "user_id": str(transfer.user_id),
                            "debit_account_id": str(transfer.sender_account_id),
                            "credit_account_id": str(transfer.receiver_account_id),
                            "amount": str(transfer.amount),
                        },
                    )
                )
        BUSINESS_OPERATIONS.labels(self.settings.service_name, "transfer", "completed").inc()

    async def _set_compensated(self, transfer_id: UUID, code: str) -> None:
        async with self.factory() as session, session.begin():
            transfer = await session.scalar(
                select(Transfer).where(Transfer.id == transfer_id).with_for_update()
            )
            if transfer and transfer.status == TransferStatus.PROCESSING:
                transfer.status = TransferStatus.COMPENSATED
                transfer.error_code = code
                transfer.completed_at = utc_now()
                session.add(
                    new_event(
                        "transfer.compensated",
                        {
                            "transfer_id": str(transfer.id),
                            "user_id": str(transfer.user_id),
                            "debit_account_id": str(transfer.receiver_account_id),
                            "credit_account_id": str(transfer.sender_account_id),
                            "amount": str(transfer.amount),
                            "error_code": code,
                        },
                    )
                )
        BUSINESS_OPERATIONS.labels(self.settings.service_name, "transfer", "compensated").inc()
