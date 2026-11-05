import json
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from uuid import UUID

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.cashback.app.models import Accrual, AccrualStatus
from services.cashback.app.rules import select_rule


async def apply_transaction(
    factory: async_sessionmaker[AsyncSession], payload: dict
) -> bool:
    transaction_id = UUID(str(payload["transaction_id"]))
    event_type = str(payload["event_type"])
    kind = "cancel" if event_type == "transaction.cancelled" else "purchase"
    async with factory() as session, session.begin():
        if await session.scalar(
            select(Accrual.id).where(
                Accrual.transaction_id == transaction_id,
                Accrual.entry_kind == kind,
            )
        ):
            return False
        amount = Decimal(str(payload["amount"]))
        occurred_at = datetime.fromisoformat(str(payload["timestamp"]))
        if kind == "cancel":
            original = await session.scalar(
                select(Accrual).where(
                    Accrual.transaction_id == transaction_id,
                    Accrual.entry_kind == "purchase",
                )
            )
            cashback = -(original.amount if original else Decimal(str(payload.get("cashback", "0"))))
            rule_id = original.rule_id if original else None
            version = original.rule_version if original else str(payload.get("rule_version", "pending"))
            status = AccrualStatus.CANCELLED
        else:
            cancellation = await session.scalar(
                select(Accrual).where(
                    Accrual.transaction_id == transaction_id,
                    Accrual.entry_kind == "cancel",
                )
            )
            rule = await select_rule(
                session, str(payload["mcc_code"]), amount, occurred_at
            )
            if not rule:
                return False
            cashback = (amount * rule.percent / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
            rule_id = rule.id
            version = rule.version
            status = AccrualStatus.CANCELLED if cancellation else AccrualStatus.EXPECTED
        session.add(
            Accrual(
                transaction_id=transaction_id,
                entry_kind=kind,
                user_id=UUID(str(payload["user_id"])),
                account_id=UUID(str(payload["account_id"])),
                source_amount=amount,
                amount=cashback,
                rule_id=rule_id,
                rule_version=version,
                status=status,
                created_at=occurred_at,
            )
        )
        return True


async def consume_transactions(
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
    for key in ("transaction.created", "transaction.cancelled"):
        await queue.bind(exchange, routing_key=key)

    async def handle(message: AbstractIncomingMessage) -> None:
        async with message.process(requeue=True):
            await apply_transaction(factory, json.loads(message.body))

    await queue.consume(handle)
