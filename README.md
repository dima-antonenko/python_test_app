# Асинхронный сервис процессинга платежей

Сервис принимает запрос на оплату, сохраняет платёж вместе с событием в одной транзакции и публикует его в RabbitMQ через outbox. Один consumer эмулирует платёжный шлюз, обновляет статус и отправляет webhook.

## Стек

FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), PostgreSQL, RabbitMQ, FastStream, Alembic, Docker Compose.

## Архитектура

1. `POST /api/v1/payments` пишет строку в `payments` и событие `payment.created` в `outbox` одной транзакцией.
2. Фоновая задача API забирает неопубликованные строки `FOR UPDATE SKIP LOCKED` и публикует их в exchange `payments` с ключом `payments.new`.
3. Consumer читает очередь `payments.new`, 2–5 секунд эмулирует шлюз (90% `succeeded`, 10% `failed`) и отправляет webhook.
4. Повторная доставка не переигрывает уже записанный статус: шлюз вызывается только пока статус `pending`.
5. Техническая ошибка (база, сеть, webhook после трёх POST) ставит сообщение в retry-очередь. После третьей неудачи оно попадает в `payments.dlq`.

Очереди:

| Очередь | Назначение |
| --- | --- |
| `payments.new` | Рабочая очередь |
| `payments.retry.1` | Повтор через 2 секунды, затем обратно в `payments.new` |
| `payments.retry.2` | Повтор через 4 секунды, затем обратно в `payments.new` |
| `payments.dlq` | Сообщения, которые не обработались за 3 попытки |

10% ошибок шлюза — это бизнес-результат `failed`, а не технический сбой. Такое сообщение подтверждается после успешного webhook.

Webhook: до 3 POST, паузы после неудач 1 с, 2 с и 4 с. Если все три не удались, срабатывает retry брокера.

## Деплой

Скрипт `scripts/deploy.sh` копирует каталог на сервер через `rsync` и запускает `docker compose` с `docker-compose.prod.yml`. Снаружи открыт только API (`:8000`). Postgres и RabbitMQ на сервере слушают `127.0.0.1`.

```bash
cp deploy.env.example deploy.env
# укажите хост; пароль — только если нет SSH-ключа
./scripts/deploy.sh
```

Нужны `ssh`, `rsync` и, при входе по паролю, `sshpass`. На сервере заранее установлены Docker и плагин Compose.

## Запуск

```bash
docker compose up --build
```

- API: http://localhost:8000
- OpenAPI: http://localhost:8000/docs
- RabbitMQ Management: http://localhost:15672 (`guest` / `guest`)
- PostgreSQL с хоста: `localhost:5433` (`payments` / `payments`, база `payments`)

Ключ по умолчанию: `dev-api-key`, заголовок `X-API-Key`.

Переменные: `DATABASE_URL`, `RABBITMQ_URL`, `API_KEY`, `OUTBOX_POLL_INTERVAL`, `WEBHOOK_TIMEOUT`. Пример есть в `.env.example`.

Webhook должен быть доступен из контейнера `consumer`. Для приёмника на хосте в compose прописан `host.docker.internal`.

Приёмник для проверки:

```bash
python3 - <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        print(self.rfile.read(size).decode())
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

HTTPServer(("0.0.0.0", 9999), Handler).serve_forever()
PY
```

## Примеры

Создание платежа:

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: dev-api-key" \
  -H "Idempotency-Key: order-1001" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.50",
    "currency": "RUB",
    "description": "Оплата заказа",
    "metadata": {"order_id": "1001"},
    "webhook_url": "http://host.docker.internal:9999/hooks/payments"
  }'
```

Ответ `202 Accepted`:

```json
{
  "payment_id": "…",
  "status": "pending",
  "created_at": "…"
}
```

Повтор с тем же `Idempotency-Key` возвращает тот же платёж и не создаёт второе событие.

Получение:

```bash
curl -s http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: dev-api-key"
```

Без ключа или с неверным ключом API отвечает `401`. Неизвестный платёж — `404`.

Статус становится `succeeded` или `failed` через несколько секунд, в карточке появляется `processed_at`. Очереди и DLQ видны в RabbitMQ Management.
