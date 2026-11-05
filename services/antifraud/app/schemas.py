from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CheckRequest(BaseModel):
    transfer_id: UUID
    sender_id: UUID
    receiver_id: UUID
    amount: Decimal = Field(gt=0)


class CheckResponse(BaseModel):
    allowed: bool
    reason_code: str
    rules_version: str
