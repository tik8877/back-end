import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import BadRequestError, ConflictError, NotFoundError
from common.events import new_event
from common.observability import BUSINESS_OPERATIONS
from common.time import utc_now
from services.accounts.app.config import Settings
from services.accounts.app.models import (
    Account,
    AccountStatus,
    Operation,
    OperationStatus,
    OperationType,
    Reservation,
    ReservationStatus,
)


def request_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class AccountService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def create_account(self, user_id: UUID, idempotency_key: str) -> Account:
        async with self.session.begin():
            existing = await self.session.scalar(
                select(Account).where(
                    Account.user_id == user_id,
                    Account.creation_key == idempotency_key,
                )
            )
            if existing:
                return existing
            account = Account(user_id=user_id, creation_key=idempotency_key)
            self.session.add(account)
            await self.session.flush()
            self.session.add(
                new_event(
                    "account.created",
                    {"account_id": str(account.id), "user_id": str(user_id), "status": account.status.value},
                )
            )
        BUSINESS_OPERATIONS.labels(self.settings.service_name, "create_account", "completed").inc()
        return account

    async def _locked_account(self, account_id: UUID) -> Account:
        account = await self.session.scalar(
            select(Account).where(Account.id == account_id).with_for_update()
        )
        if not account:
            raise NotFoundError("ACCOUNT_NOT_FOUND", "Счёт не найден")
        return account

    async def _existing_operation(
        self,
        account_id: UUID,
        key: str,
        digest: str,
    ) -> Operation | None:
        operation = await self.session.scalar(
            select(Operation).where(
                Operation.account_id == account_id,
                Operation.idempotency_key == key,
            )
        )
        if operation and operation.request_hash != digest:
            raise BadRequestError(
                "IDEMPOTENCY_KEY_REUSE",
                "Ключ уже использован для другого запроса",
            )
        return operation

    def _result(self, account: Account, operation_id: UUID, operation_type: OperationType) -> dict:
        return {
            "operation_id": str(operation_id),
            "account_id": str(account.id),
            "type": operation_type.value,
            "balance": str(account.balance),
            "available_balance": str(account.available_balance),
            "status": "completed",
        }

    async def _change_balance(
        self,
        account_id: UUID,
        amount: Decimal,
        key: str,
        digest: str,
        operation_type: OperationType,
    ) -> Operation:
        async with self.session.begin():
            account = await self._locked_account(account_id)
            previous = await self._existing_operation(account_id, key, digest)
            if previous:
                return previous
            if account.status == AccountStatus.CLOSED:
                raise ConflictError("ACCOUNT_CLOSED", "Счёт закрыт")
            if operation_type == OperationType.WITHDRAW:
                if account.status == AccountStatus.BLOCKED:
                    raise ConflictError("ACCOUNT_BLOCKED", "Расходные операции запрещены")
                if account.available_balance < amount:
                    raise ConflictError("INSUFFICIENT_FUNDS", "Недостаточно доступных средств")
                account.balance -= amount
                account.available_balance -= amount
            else:
                account.balance += amount
                account.available_balance += amount
                if account.status == AccountStatus.CREATED:
                    account.status = AccountStatus.ACTIVE
            account.last_operation_at = utc_now()
            account.version += 1
            operation = Operation(
                account_id=account.id,
                type=operation_type,
                amount=amount,
                idempotency_key=key,
                request_hash=digest,
                status=OperationStatus.COMPLETED,
            )
            self.session.add(operation)
            await self.session.flush()
            operation.response_body = self._result(account, operation.id, operation_type)
            self.session.add(
                new_event(
                    "account.balance_changed",
                    {
                        "account_id": str(account.id),
                        "user_id": str(account.user_id),
                        "operation_id": str(operation.id),
                        "operation": operation_type.value,
                    },
                )
            )
        BUSINESS_OPERATIONS.labels(
            self.settings.service_name, operation_type.value, "completed"
        ).inc()
        return operation

    async def deposit(self, account_id: UUID, amount: Decimal, key: str, digest: str) -> Operation:
        return await self._change_balance(
            account_id, amount, key, digest, OperationType.DEPOSIT
        )

    async def withdraw(self, account_id: UUID, amount: Decimal, key: str, digest: str) -> Operation:
        return await self._change_balance(
            account_id, amount, key, digest, OperationType.WITHDRAW
        )

    async def reserve(
        self, account_id: UUID, amount: Decimal, key: str, digest: str
    ) -> Reservation:
        async with self.session.begin():
            account = await self._locked_account(account_id)
            previous = await self._existing_operation(account_id, key, digest)
            if previous and previous.response_body:
                reservation_id = UUID(previous.response_body["reservation_id"])
                reservation = await self.session.get(Reservation, reservation_id)
                if reservation:
                    return reservation
            if account.status in {AccountStatus.BLOCKED, AccountStatus.CLOSED}:
                raise ConflictError("ACCOUNT_UNAVAILABLE", "Расходные операции запрещены")
            if account.available_balance < amount:
                raise ConflictError("INSUFFICIENT_FUNDS", "Недостаточно доступных средств")
            account.available_balance -= amount
            account.last_operation_at = utc_now()
            account.version += 1
            reservation = Reservation(
                account_id=account.id,
                amount=amount,
                expires_at=utc_now() + timedelta(seconds=self.settings.reservation_ttl_seconds),
            )
            operation = Operation(
                account_id=account.id,
                type=OperationType.RESERVE,
                amount=amount,
                idempotency_key=key,
                request_hash=digest,
                status=OperationStatus.COMPLETED,
            )
            self.session.add_all([reservation, operation])
            await self.session.flush()
            operation.response_body = {
                "operation_id": str(operation.id),
                "reservation_id": str(reservation.id),
                "account_id": str(account.id),
                "status": reservation.status.value,
                "expires_at": reservation.expires_at.isoformat(),
            }
        BUSINESS_OPERATIONS.labels(self.settings.service_name, "reserve", "completed").inc()
        return reservation

    async def finish_reservation(
        self,
        reservation_id: UUID,
        key: str,
        confirm: bool,
    ) -> Reservation:
        operation_type = OperationType.RESERVE_CONFIRM if confirm else OperationType.RESERVE_CANCEL
        digest = request_digest({"reservation_id": str(reservation_id), "action": operation_type.value})
        expired = False
        async with self.session.begin():
            reservation = await self.session.scalar(
                select(Reservation)
                .where(Reservation.id == reservation_id)
                .with_for_update()
            )
            if not reservation:
                raise NotFoundError("RESERVATION_NOT_FOUND", "Резерв не найден")
            account = await self._locked_account(reservation.account_id)
            previous = await self._existing_operation(account.id, key, digest)
            if previous:
                return reservation
            if confirm and reservation.status == ReservationStatus.CONFIRMED:
                return reservation
            if not confirm and reservation.status == ReservationStatus.CANCELLED:
                return reservation
            if reservation.status != ReservationStatus.ACTIVE:
                raise ConflictError("RESERVATION_NOT_ACTIVE", "Резерв уже завершён")
            if reservation.expires_at <= utc_now():
                account.available_balance += reservation.amount
                reservation.status = ReservationStatus.EXPIRED
                account.last_operation_at = utc_now()
                account.version += 1
                self.session.add(
                    new_event(
                        "reservation.expired",
                        {"reservation_id": str(reservation.id), "account_id": str(account.id)},
                    )
                )
                expired = True
            else:
                if confirm:
                    account.balance -= reservation.amount
                    reservation.status = ReservationStatus.CONFIRMED
                else:
                    account.available_balance += reservation.amount
                    reservation.status = ReservationStatus.CANCELLED
                account.last_operation_at = utc_now()
                account.version += 1
                operation = Operation(
                    account_id=account.id,
                    type=operation_type,
                    amount=reservation.amount,
                    idempotency_key=key,
                    request_hash=digest,
                    status=OperationStatus.COMPLETED,
                )
                self.session.add(operation)
                await self.session.flush()
                operation.response_body = {
                    "operation_id": str(operation.id),
                    "reservation_id": str(reservation.id),
                    "status": reservation.status.value,
                }
                self.session.add(
                    new_event(
                        f"reservation.{reservation.status.value}",
                        {"reservation_id": str(reservation.id), "account_id": str(account.id)},
                    )
                )
        if expired:
            raise ConflictError("RESERVATION_EXPIRED", "Срок резерва истёк")
        return reservation

    async def close_account(self, account_id: UUID, key: str) -> Operation:
        digest = request_digest({"account_id": str(account_id), "action": "close"})
        async with self.session.begin():
            account = await self._locked_account(account_id)
            previous = await self._existing_operation(account_id, key, digest)
            if previous:
                return previous
            if account.status == AccountStatus.CLOSED:
                raise ConflictError("ACCOUNT_CLOSED", "Счёт уже закрыт")
            active_count = await self.session.scalar(
                select(func.count())
                .select_from(Reservation)
                .where(
                    Reservation.account_id == account.id,
                    Reservation.status == ReservationStatus.ACTIVE,
                )
            )
            idle_since = account.last_operation_at or account.created_at
            cutoff = utc_now() - timedelta(days=self.settings.close_account_min_idle_days)
            if account.balance != 0:
                raise ConflictError("NON_ZERO_BALANCE", "Для закрытия остаток должен быть нулевым")
            if active_count:
                raise ConflictError("ACTIVE_RESERVATIONS", "Есть активные резервы")
            if idle_since >= cutoff:
                raise ConflictError("ACCOUNT_NOT_IDLE", "С момента последней операции прошло недостаточно времени")
            account.status = AccountStatus.CLOSED
            account.version += 1
            operation = Operation(
                account_id=account.id,
                type=OperationType.CLOSE,
                amount=Decimal("0.00"),
                idempotency_key=key,
                request_hash=digest,
                status=OperationStatus.COMPLETED,
            )
            self.session.add(operation)
            await self.session.flush()
            operation.response_body = self._result(account, operation.id, OperationType.CLOSE)
            self.session.add(
                new_event(
                    "account.closed",
                    {"account_id": str(account.id), "user_id": str(account.user_id)},
                )
            )
        return operation

    async def operation_by_key(self, key: str) -> Operation:
        operation = await self.session.scalar(
            select(Operation).where(Operation.idempotency_key == key).order_by(Operation.created_at.desc())
        )
        if not operation:
            raise NotFoundError("OPERATION_NOT_FOUND", "Операция не найдена")
        return operation
