from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from services.notification.app.models import NotificationStatus


class SubscriptionRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    event_type: str
    created_at: datetime
    unsubscribed_at: datetime | None


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    event_type: str
    status: NotificationStatus
    attempts: int
    created_at: datetime
    sent_at: datetime | None
