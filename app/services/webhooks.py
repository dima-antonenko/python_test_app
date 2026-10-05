import asyncio
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

WEBHOOK_BACKOFF_SECONDS = (1, 2, 4)


class WebhookDeliveryError(Exception):
    pass


async def send_webhook(url: str, payload: dict[str, Any]) -> None:
    timeout = get_settings().webhook_timeout
    attempts = len(WEBHOOK_BACKOFF_SECONDS)
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt, delay in enumerate(WEBHOOK_BACKOFF_SECONDS, start=1):
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "webhook attempt %s/%s failed url=%s error=%s",
                    attempt,
                    attempts,
                    url,
                    exc,
                )
            else:
                logger.info("webhook delivered url=%s status=%s", url, response.status_code)
                return
            await asyncio.sleep(delay)
    raise WebhookDeliveryError(f"webhook delivery failed for {url}") from last_error
