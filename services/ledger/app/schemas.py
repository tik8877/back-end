from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TransferEvent(BaseModel):
    transfer_id: UUID
    debit_account_id: UUID
    credit_account_id: UUID
    amount: Decimal = Field(gt=0)
    timestamp: datetime


class EntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transfer_id: UUID
    debit_account_id: UUID
    credit_account_id: UUID
    amount: Decimal
    timestamp: datetime


class StatementPage(BaseModel):
    items: list[EntryResponse]
    next_timestamp: datetime | None
    next_id: UUID | None


class BalanceResponse(BaseModel):
    account_id: UUID
    balance: Decimal
