import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker

from app.api.v1.payments import router as payments_router
from app.broker.topology import declare_topology
from app.config import get_settings
from app.db import engine
from app.services.outbox import run_outbox_relay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    broker = RabbitBroker(get_settings().rabbitmq_url)
    await broker.connect()
    await declare_topology(broker)
    relay = asyncio.create_task(run_outbox_relay(broker))
    logger.info("outbox relay started")
    try:
        yield
    finally:
        relay.cancel()
        with suppress(asyncio.CancelledError):
            await relay
        await broker.stop()
        await engine.dispose()


app = FastAPI(title="Payment processing", lifespan=lifespan)
app.include_router(payments_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
