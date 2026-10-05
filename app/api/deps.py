import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def require_api_key(
    x_api_key: Annotated[
        str | None,
        Header(
            alias="X-API-Key",
            description="Ключ доступа. На этом стенде работает значение `dev-api-key`.",
            examples=["dev-api-key"],
            openapi_examples={
                "stand": {
                    "summary": "Ключ стенда",
                    "description": "Значение API_KEY по умолчанию",
                    "value": "dev-api-key",
                }
            },
        ),
    ] = None,
) -> None:
    expected = get_settings().api_key
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
