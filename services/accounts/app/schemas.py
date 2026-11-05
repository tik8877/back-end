from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.accounts.app.models import AccountStatus, OperationStatus, OperationType, ReservationStatus


class MoneyRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)

    @field_validator("amount")
    @classmethod
    def two_decimal_places(cls, value: Decimal) -> Decimal:
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("Сумма должна иметь не более двух знаков после запятой")
        return value


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    balance: Decimal
    available_balance: Decimal
    status: AccountStatus
    last_operation_at: datetime | None
    created_at: datetime


class OperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    type: OperationType
    amount: Decimal
    status: OperationStatus
    response_body: dict | None
    created_at: datetime


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    amount: Decimal
    expires_at: datetime
    status: ReservationStatus
