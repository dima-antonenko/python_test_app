import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import SessionDep, require_api_key
from app.schemas.payment import PaymentAccepted, PaymentCreate, PaymentRead, to_payment_read
from app.services.payments import create_payment, get_payment

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentAccepted,
    description=(
        "Рабочие значения заголовков на этом стенде:\n\n"
        "- **X-API-Key:** `dev-api-key`\n"
        "- **Idempotency-Key:** любая непустая строка, например `order-1001`. "
        "Повтор с тем же ключом возвращает уже созданный платёж."
    ),
)
async def create_payment_endpoint(
    body: PaymentCreate,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=255,
            description=(
                "Ключ идемпотентности. Пример, с которым запрос принимается: `order-1001`. "
                "Повтор с тем же ключом и тем же телом возвращает тот же платёж."
            ),
            examples=["order-1001"],
            openapi_examples={
                "order": {
                    "summary": "Ключ заказа",
                    "value": "order-1001",
                }
            },
        ),
    ],
) -> PaymentAccepted:
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must not be blank",
        )
    payment = await create_payment(session, body, key)
    return PaymentAccepted(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment_endpoint(payment_id: uuid.UUID, session: SessionDep) -> PaymentRead:
    payment = await get_payment(session, payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return to_payment_read(payment)
