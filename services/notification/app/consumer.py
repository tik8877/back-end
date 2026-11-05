import json
from datetime import UTC, datetime
from uuid import UUID

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.time import utc_now
from services.notification.app.config import Settings
from services.notification.app.models import NotificationStatus, SentNotification, Subscription
from services.notification.app.sender import DeliveryFailed, TelegramSender


async def process_event(
    factory: async_sessionmaker[AsyncSession],
    sender: TelegramSender,
    settings: Settings,
    payload: dict,
) -> tuple[str, int]:
    event_id = UUID(str(payload["event_id"]))
    user_id = UUID(str(payload["user_id"]))
    event_type = str(payload["event_type"])
    event_time = datetime.fromisoformat(str(payload["timestamp"]))
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(SentNotification)
            .where(SentNotification.event_id == event_id)
            .with_for_update()
        )
        if row and row.status in {
            NotificationStatus.SENT,
            NotificationStatus.SKIPPED,
            NotificationStatus.MANUAL_REVIEW,
        }:
            return "done", row.attempts
        subscription = await session.scalar(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.event_type == event_type,
            )
        )
        subscribed_at = subscription.created_at if subscription else None
        if subscribed_at and subscribed_at.tzinfo is None:
            subscribed_at = subscribed_at.replace(tzinfo=UTC)
        inactive = (
            subscription is None
            or subscription.unsubscribed_at is not None
            or event_time < subscribed_at
        )
        if row is None:
            row = SentNotification(
                event_id=event_id,
                user_id=user_id,
                event_type=event_type,
                status=NotificationStatus.PROCESSING,
            )
            session.add(row)
            await session.flush()
        if inactive:
            row.status = NotificationStatus.SKIPPED
            return "done", row.attempts
        row.status = NotificationStatus.PROCESSING
        attempt = row.attempts + 1

    try:
        await sender.send(str(event_id), str(user_id), event_type)
    except DeliveryFailed as exc:
        async with factory() as session, session.begin():
            row = await session.scalar(
                select(SentNotification)
                .where(SentNotification.event_id == event_id)
                .with_for_update()
            )
            if not row:
                return "done", attempt
            row.attempts = attempt
            row.last_error = exc.reason
            if attempt >= settings.max_delivery_attempts:
                row.status = NotificationStatus.MANUAL_REVIEW
                return "manual", attempt
            row.status = NotificationStatus.WAITING
            delay = exc.delay_seconds or min(
                settings.delivery_delay_base_seconds * (2 ** (attempt - 1)),
                settings.delivery_delay_max_seconds,
            )
            return "later", delay

    async with factory() as session, session.begin():
        row = await session.scalar(
            select(SentNotification)
            .where(SentNotification.event_id == event_id)
            .with_for_update()
        )
        if row:
            row.status = NotificationStatus.SENT
            row.attempts = attempt
            row.sent_at = utc_now()
            row.last_error = None
    return "done", attempt


async def consume_notifications(
    connection: AbstractRobustConnection,
    factory: async_sessionmaker[AsyncSession],
    sender: TelegramSender,
    settings: Settings,
) -> None:
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=settings.prefetch_count)
    exchange = await channel.declare_exchange(
        "events", aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue(settings.queue_name, durable=True)
    for key in ("account.*", "transfer.*"):
        await queue.bind(exchange, routing_key=key)
    dead_queue = await channel.declare_queue(settings.dead_queue_name, durable=True)

    async def handle(message: AbstractIncomingMessage) -> None:
        payload = json.loads(message.body)
        action, value = await process_event(factory, sender, settings, payload)
        if action == "later":
            delay_queue = await channel.declare_queue(
                f"notification.delay.{value}",
                durable=True,
                arguments={
                    "x-message-ttl": value * 1000,
                    "x-dead-letter-exchange": "events",
                    "x-dead-letter-routing-key": payload["event_type"],
                },
            )
            await channel.default_exchange.publish(
                aio_pika.Message(
                    message.body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=delay_queue.name,
            )
        elif action == "manual":
            await channel.default_exchange.publish(
                aio_pika.Message(
                    message.body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=dead_queue.name,
            )
        await message.ack()

    await queue.consume(handle)
