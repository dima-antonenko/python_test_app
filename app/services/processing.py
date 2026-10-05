import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update

from app.db import session_factory
from app.models.payment import Payment, PaymentStatus
from app.services.webhooks import send_webhook

logger = logging.getLogger(__name__)

_GATEWAY_SUCCESS_RATE = 0.9


class PaymentNotFoundError(Exception):
    def __init__(self, payment_id: uuid.UUID) -> None:
        self.payment_id = payment_id
        super().__init__(f"payment {payment_id} not found")


def build_webhook_payload(payment: Payment) -> dict[str, Any]:
    return {
        "payment_id": str(payment.id),
        "status": payment.status.value,
        "amount": str(payment.amount),
        "currency": payment.currency.value,
        "description": payment.description,
        "metadata": dict(payment.metadata_ or {}),
        "created_at": payment.created_at.isoformat(),
        "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
    }


async def process_payment(payment_id: uuid.UUID) -> None:
    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None:
            raise PaymentNotFoundError(payment_id)
        status = payment.status

    if status == PaymentStatus.pending:
        delay = random.uniform(2, 5)
        logger.info("emulating gateway payment_id=%s delay=%.2fs", payment_id, delay)
        await asyncio.sleep(delay)
        outcome = (
            PaymentStatus.succeeded if random.random() < _GATEWAY_SUCCESS_RATE else PaymentStatus.failed
        )
        logger.info("gateway result payment_id=%s status=%s", payment_id, outcome.value)
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Payment)
                    .where(Payment.id == payment_id, Payment.status == PaymentStatus.pending)
                    .values(status=outcome, processed_at=datetime.now(timezone.utc))
                )

    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None:
            raise PaymentNotFoundError(payment_id)
        if payment.status == PaymentStatus.pending:
            raise RuntimeError(f"payment {payment_id} is still pending after processing")
        url = payment.webhook_url
        payload = build_webhook_payload(payment)

    await send_webhook(url, payload)
