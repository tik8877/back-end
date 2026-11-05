from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from services.external.app.models import SyncStatus


class SyncRequest(BaseModel):
    date_from: datetime
    date_to: datetime


class SyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: SyncStatus
    last_processed_cursor: str | None
    total_pages: int | None
    processed_pages: int
    error: str | None
    created_at: datetime
    completed_at: datetime | None
