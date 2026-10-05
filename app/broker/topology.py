import logging
from typing import Any

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

logger = logging.getLogger(__name__)

PAYMENTS_EXCHANGE_NAME = "payments"
DLX_EXCHANGE_NAME = "payments.dlx"
PAYMENTS_ROUTING_KEY = "payments.new"
DLQ_ROUTING_KEY = "payments.dlq"
RETRY_ROUTING_KEYS = ("payments.retry.1", "payments.retry.2")
RETRY_TTL_MS = (2_000, 4_000)
MAX_ATTEMPTS = 3

payments_exchange = RabbitExchange(
    PAYMENTS_EXCHANGE_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)
dlx_exchange = RabbitExchange(
    DLX_EXCHANGE_NAME,
    type=ExchangeType.DIRECT,
    durable=True,
)

payments_queue = RabbitQueue(
    PAYMENTS_ROUTING_KEY,
    durable=True,
    routing_key=PAYMENTS_ROUTING_KEY,
)

retry_queues = tuple(
    RabbitQueue(
        routing_key,
        durable=True,
        routing_key=routing_key,
        arguments={
            "x-message-ttl": ttl_ms,
            "x-dead-letter-exchange": PAYMENTS_EXCHANGE_NAME,
            "x-dead-letter-routing-key": PAYMENTS_ROUTING_KEY,
        },
    )
    for routing_key, ttl_ms in zip(RETRY_ROUTING_KEYS, RETRY_TTL_MS, strict=True)
)

dlq = RabbitQueue(
    DLQ_ROUTING_KEY,
    durable=True,
    routing_key=DLQ_ROUTING_KEY,
)


async def declare_topology(broker: RabbitBroker) -> None:
    payments_ex = await broker.declare_exchange(payments_exchange)
    dlx_ex = await broker.declare_exchange(dlx_exchange)

    bindings: tuple[tuple[RabbitQueue, str, object], ...] = (
        (payments_queue, PAYMENTS_ROUTING_KEY, payments_ex),
        (retry_queues[0], RETRY_ROUTING_KEYS[0], payments_ex),
        (retry_queues[1], RETRY_ROUTING_KEYS[1], payments_ex),
        (dlq, DLQ_ROUTING_KEY, dlx_ex),
    )
    for queue, routing_key, exchange in bindings:
        declared = await broker.declare_queue(queue)
        await declared.bind(exchange, routing_key=routing_key)


async def publish_message(
    broker: RabbitBroker,
    payload: dict[str, Any],
    *,
    exchange: RabbitExchange,
    routing_key: str,
    headers: dict[str, Any] | None = None,
) -> None:
    await broker.publish(
        payload,
        exchange=exchange,
        routing_key=routing_key,
        headers=headers,
        persist=True,
    )


async def schedule_retry(broker: RabbitBroker, payload: dict[str, Any], retry_count: int) -> None:
    next_count = retry_count + 1
    headers = {"x-retry-count": next_count}
    if next_count >= MAX_ATTEMPTS:
        await publish_message(
            broker,
            payload,
            exchange=dlx_exchange,
            routing_key=DLQ_ROUTING_KEY,
            headers=headers,
        )
        logger.error("message sent to DLQ payload=%s attempts=%s", payload, next_count)
        return

    routing_key = RETRY_ROUTING_KEYS[next_count - 1]
    await publish_message(
        broker,
        payload,
        exchange=payments_exchange,
        routing_key=routing_key,
        headers=headers,
    )
    logger.warning(
        "message scheduled for retry payload=%s attempt=%s queue=%s",
        payload,
        next_count,
        routing_key,
    )


async def publish_to_dlq(broker: RabbitBroker, payload: dict[str, Any], retry_count: int) -> None:
    await publish_message(
        broker,
        payload,
        exchange=dlx_exchange,
        routing_key=DLQ_ROUTING_KEY,
        headers={"x-retry-count": retry_count},
    )
    logger.error("message sent to DLQ payload=%s retry_count=%s", payload, retry_count)
