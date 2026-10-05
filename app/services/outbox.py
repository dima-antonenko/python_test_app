import asyncio
import logging
from datetime import datetime, timezone

from faststream.rabbit import RabbitBroker
from sqlalchemy import select

from app.broker.topology import PAYMENTS_ROUTING_KEY, payments_exchange, publish_message
from app.config import get_settings
from app.db import session_factory
from app.models.outbox import Outbox

logger = logging.getLogger(__name__)

_BATCH_LIMIT = 50


async def publish_pending(broker: RabbitBroker) -> None:
    for _ in range(_BATCH_LIMIT):
        if not await _publish_one(broker):
            return


async def _publish_one(broker: RabbitBroker) -> bool:
    async with session_factory() as session:
        async with session.begin():
            row = (
                await session.execute(
                    select(Outbox)
                    .where(Outbox.published_at.is_(None))
                    .order_by(Outbox.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            try:
                await publish_message(
                    broker,
                    row.payload,
                    exchange=payments_exchange,
                    routing_key=PAYMENTS_ROUTING_KEY,
                )
            except Exception:
                row.attempts += 1
                logger.exception("failed to publish outbox id=%s", row.id)
                return False
            row.published_at = datetime.now(timezone.utc)
            logger.info(
                "published outbox id=%s aggregate_id=%s event=%s",
                row.id,
                row.aggregate_id,
                row.event_type,
            )
            return True


async def run_outbox_relay(broker: RabbitBroker) -> None:
    interval = get_settings().outbox_poll_interval
    while True:
        try:
            await publish_pending(broker)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox relay failed")
        await asyncio.sleep(interval)
