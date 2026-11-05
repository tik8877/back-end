from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.errors import BadRequestError
from common.time import utc_now
from services.notification.app.db import get_session
from services.notification.app.models import SentNotification, Subscription
from services.notification.app.schemas import NotificationResponse, SubscriptionRequest, SubscriptionResponse


router = APIRouter(prefix="/notifications", tags=["notification"])


def user_header(request: Request) -> UUID:
    try:
        return UUID(request.headers.get("X-User-Id", ""))
    except ValueError as exc:
        raise BadRequestError("USER_ID_REQUIRED", "Заголовок X-User-Id обязателен") from exc


@router.post("/subscribe", response_model=SubscriptionResponse)
async def subscribe(
    body: SubscriptionRequest,
    user_id: Annotated[UUID, Depends(user_header)],
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        row = await session.scalar(
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.event_type == body.event_type)
            .with_for_update()
        )
        if row:
            if row.unsubscribed_at:
                row.created_at = utc_now()
                row.unsubscribed_at = None
            return row
        row = Subscription(user_id=user_id, event_type=body.event_type)
        session.add(row)
        await session.flush()
        return row


@router.post("/unsubscribe", response_model=SubscriptionResponse)
async def unsubscribe(
    body: SubscriptionRequest,
    user_id: Annotated[UUID, Depends(user_header)],
    session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        row = await session.scalar(
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.event_type == body.event_type)
            .with_for_update()
        )
        if not row:
            row = Subscription(
                user_id=user_id,
                event_type=body.event_type,
                unsubscribed_at=utc_now(),
            )
            session.add(row)
            await session.flush()
        elif row.unsubscribed_at is None:
            row.unsubscribed_at = utc_now()
        return row


@router.get("/history", response_model=list[NotificationResponse])
async def history(
    user_id: Annotated[UUID, Depends(user_header)],
    session: AsyncSession = Depends(get_session),
):
    return list(
        (
            await session.scalars(
                select(SentNotification)
                .where(SentNotification.user_id == user_id)
                .order_by(SentNotification.created_at.desc())
                .limit(200)
            )
        ).all()
    )
