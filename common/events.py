import asyncio
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import aio_pika
import structlog
from aio_pika.abc import AbstractRobustChannel, AbstractRobustConnection
from sqlalchemy import JSON, DateTime, Integer, String, Uuid, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base
from common.time import utc_now


class PendingEvent(Base):
    __tablename__ = "pending_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


def new_event(event_type: str, payload: dict[str, Any]) -> PendingEvent:
    body = dict(payload)
    body.setdefault("event_id", str(uuid4()))
    body.setdefault("event_type", event_type)
    body.setdefault("timestamp", utc_now().isoformat())
    return PendingEvent(event_type=event_type, payload=body)


async def connect_broker(
    url: str,
    attempts: int,
    initial_delay_seconds: float,
    max_delay_seconds: float,
) -> AbstractRobustConnection:
    delay = initial_delay_seconds
    for attempt in range(1, attempts + 1):
        try:
            return await aio_pika.connect_robust(url)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            structlog.get_logger().warning(
                "broker_connection_failed",
                details={"attempt": attempt, "error_type": type(exc).__name__},
            )
            if attempt == attempts:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay_seconds)
    raise RuntimeError("Не удалось подключиться к брокеру")


async def publish_pending_events(
    factory: async_sessionmaker[AsyncSession],
    channel: AbstractRobustChannel,
    batch_size: int,
) -> int:
    exchange = await channel.declare_exchange(
        "events", aio_pika.ExchangeType.TOPIC, durable=True
    )
    async with factory() as session, session.begin():
        rows = list(
            (
                await session.scalars(
                    select(PendingEvent)
                    .where(PendingEvent.published_at.is_(None))
                    .order_by(PendingEvent.created_at)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for row in rows:
            try:
                await exchange.publish(
                    aio_pika.Message(
                        json.dumps(row.payload, ensure_ascii=False, default=str).encode(),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        message_id=str(row.id),
                        content_type="application/json",
                    ),
                    routing_key=row.event_type,
                    mandatory=True,
                )
                row.published_at = utc_now()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                row.attempts += 1
                structlog.get_logger().warning(
                    "event_publish_failed",
                    details={"event_id": str(row.id), "error_type": type(exc).__name__},
                )
        return len(rows)


async def publisher_worker(
    factory: async_sessionmaker[AsyncSession],
    channel: AbstractRobustChannel,
    interval_seconds: float,
    batch_size: int,
) -> None:
    while True:
        await publish_pending_events(factory, channel, batch_size)
        await asyncio.sleep(interval_seconds)
