import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base
from common.time import utc_now


class AccrualStatus(str, enum.Enum):
    EXPECTED = "expected"
    CREDITED = "credited"
    CANCELLED = "cancelled"


class CashbackRule(Base):
    __tablename__ = "cashback_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mcc_code: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    max_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[str] = mapped_column(String(64), nullable=False)


class Accrual(Base):
    __tablename__ = "accruals"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    source_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    rule_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AccrualStatus] = mapped_column(
        Enum(AccrualStatus, native_enum=False), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    credited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("transaction_id", "entry_kind", name="uq_accrual_transaction_kind"),
    )


class PeriodCredit(Base):
    __tablename__ = "cashback_period_credits"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "period_start", name="uq_cashback_user_period"),
    )
