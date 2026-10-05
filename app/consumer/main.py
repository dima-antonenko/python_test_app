import logging
import uuid
from typing import Any

from faststream import AckPolicy, FastStream
from faststream.rabbit import RabbitBroker, RabbitMessage
from pydantic import BaseModel

from app.broker.topology import (
    declare_topology,
    payments_exchange,
    payments_queue,
    publish_to_dlq,
    schedule_retry,
)
from app.config import get_settings
from app.db import engine
from app.services.processing import PaymentNotFoundError, process_payment
from app.services.webhooks import WebhookDeliveryError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)

broker = RabbitBroker(get_settings().rabbitmq_url)


class PaymentEvent(BaseModel):
    payment_id: uuid.UUID


def _payload(event: PaymentEvent) -> dict[str, str]:
    return {"payment_id": str(event.payment_id)}


def _retry_count(message: RabbitMessage) -> int:
    raw: Any = message.headers.get("x-retry-count", 0)
    if isinstance(raw, bytes):
        raw = raw.decode()
    if raw in (None, ""):
        return 0
    return int(raw)


@broker.subscriber(
    payments_queue,
    payments_exchange,
    ack_policy=AckPolicy.NACK_ON_ERROR,
)
async def handle_payment(event: PaymentEvent, message: RabbitMessage) -> None:
    retry_count = _retry_count(message)
    logger.info("received payment_id=%s retry_count=%s", event.payment_id, retry_count)
    try:
        await process_payment(event.payment_id)
    except PaymentNotFoundError:
        logger.error("payment %s does not exist", event.payment_id)
        await publish_to_dlq(broker, _payload(event), retry_count)
        return
    except WebhookDeliveryError as exc:
        logger.error(
            "payment %s webhook failed, retry_count=%s error=%s",
            event.payment_id,
            retry_count,
            exc,
        )
        await schedule_retry(broker, _payload(event), retry_count)
        return
    except Exception:
        logger.exception(
            "payment %s failed, retry_count=%s",
            event.payment_id,
            retry_count,
        )
        await schedule_retry(broker, _payload(event), retry_count)
        return
    logger.info("payment %s done", event.payment_id)


app = FastStream(broker)


@app.after_startup
async def setup_topology() -> None:
    await declare_topology(broker)


@app.after_shutdown
async def close_db() -> None:
    await engine.dispose()
