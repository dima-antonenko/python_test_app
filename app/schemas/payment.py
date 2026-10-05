import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models.payment import Currency, Payment, PaymentStatus

_MAX_AMOUNT = Decimal("10000000000000000")  # Numeric(18, 2)


class PaymentCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "amount": "100.50",
                    "currency": "RUB",
                    "description": "Оплата заказа",
                    "metadata": {"order_id": "1001"},
                    "webhook_url": "https://example.com/hooks/payments",
                }
            ]
        }
    )

    amount: Decimal
    currency: Currency
    description: str = Field(min_length=1, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> Decimal:
        try:
            amount = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("amount must be a decimal") from exc
        if not amount.is_finite() or amount <= 0 or amount >= _MAX_AMOUNT:
            raise ValueError("amount must be a positive decimal with up to 18 digits")
        quantized = amount.quantize(Decimal("0.01"))
        if quantized != amount:
            raise ValueError("amount must have at most 2 decimal places")
        return quantized

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("description must not be blank")
        return cleaned


class PaymentAccepted(BaseModel):
    payment_id: uuid.UUID
    status: PaymentStatus
    created_at: datetime


class PaymentRead(BaseModel):
    id: uuid.UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None


def to_payment_read(payment: Payment) -> PaymentRead:
    return PaymentRead(
        id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=dict(payment.metadata_ or {}),
        status=payment.status,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )
