from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Numeric, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base
from common.time import utc_now


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transfer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    debit_account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    credit_account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        Index("ix_entries_debit_timestamp_id", "debit_account_id", "timestamp", "id"),
        Index("ix_entries_credit_timestamp_id", "credit_account_id", "timestamp", "id"),
        UniqueConstraint("transfer_id", name="uq_entry_transfer"),
    )
