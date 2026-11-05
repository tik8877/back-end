from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from services.payments.app.models import TransferStatus


class TransferCreate(BaseModel):
    sender_account_id: UUID
    receiver_account_id: UUID
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)


class TransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_account_id: UUID
    receiver_account_id: UUID
    amount: Decimal
    status: TransferStatus
    antifraud_reason: str | None
    reservation_id: UUID | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
