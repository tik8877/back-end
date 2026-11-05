import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.ledger.app.models import Entry


async def record_transfer(
    factory: async_sessionmaker[AsyncSession], payload: dict
) -> bool:
    transfer_id = UUID(str(payload["transfer_id"]))
    async with factory() as session:
        try:
            async with session.begin():
                existing = await session.scalar(
                    select(Entry.id).where(Entry.transfer_id == transfer_id)
                )
                if existing:
                    return False
                session.add(
                    Entry(
                        transfer_id=transfer_id,
                        debit_account_id=UUID(str(payload["debit_account_id"])),
                        credit_account_id=UUID(str(payload["credit_account_id"])),
                        amount=Decimal(str(payload["amount"])),
                        timestamp=(
                            datetime.fromisoformat(payload["timestamp"])
                            if isinstance(payload["timestamp"], str)
                            else payload["timestamp"]
                        ),
                    )
                )
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def consume_transfers(
    connection: AbstractRobustConnection,
    factory: async_sessionmaker[AsyncSession],
    queue_name: str,
    prefetch_count: int,
) -> None:
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=prefetch_count)
    exchange = await channel.declare_exchange(
        "events", aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue(queue_name, durable=True)
    await queue.bind(exchange, routing_key="transfer.completed")
    await queue.bind(exchange, routing_key="transfer.compensated")

    async def handle(message: AbstractIncomingMessage) -> None:
        async with message.process(requeue=True, ignore_processed=True):
            await record_transfer(factory, json.loads(message.body))

    await queue.consume(handle)
