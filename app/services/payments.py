import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import Outbox
from app.models.payment import Payment, PaymentStatus
from app.schemas.payment import PaymentCreate

EVENT_PAYMENT_CREATED = "payment.created"


async def get_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment | None:
    return await session.get(Payment, payment_id)


async def _get_by_idempotency_key(session: AsyncSession, key: str) -> Payment | None:
    return await session.scalar(select(Payment).where(Payment.idempotency_key == key))


async def create_payment(session: AsyncSession, data: PaymentCreate, idempotency_key: str) -> Payment:
    existing = await _get_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing

    payment_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    payment = Payment(
        id=payment_id,
        amount=data.amount,
        currency=data.currency,
        description=data.description,
        metadata_=data.metadata,
        status=PaymentStatus.pending,
        idempotency_key=idempotency_key,
        webhook_url=str(data.webhook_url),
        created_at=now,
    )
    outbox = Outbox(
        id=uuid.uuid4(),
        aggregate_id=payment_id,
        event_type=EVENT_PAYMENT_CREATED,
        payload={"payment_id": str(payment_id)},
        created_at=now,
        attempts=0,
    )
    session.add(payment)
    try:
        await session.flush()
        session.add(outbox)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _get_by_idempotency_key(session, idempotency_key)
        if existing is None:
            raise
        return existing
    return payment
