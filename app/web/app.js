const historyKey = "payments-ui-history";
const apiKeyStorage = "payments-ui-api-key";

const form = document.querySelector("#payment-form");
const lookupForm = document.querySelector("#lookup-form");
const card = document.querySelector("#card");
const historyList = document.querySelector("#history");
const formError = document.querySelector("#form-error");
const lookupError = document.querySelector("#lookup-error");
const submitButton = document.querySelector("#submit");
const apiKeyInput = document.querySelector("#api-key");
const idempotencyInput = document.querySelector("#idempotency");

let pollToken = 0;

apiKeyInput.value = localStorage.getItem(apiKeyStorage) || "dev-api-key";
idempotencyInput.value = newIdempotencyKey();
renderHistory();

document.querySelector("#new-key").addEventListener("click", () => {
  idempotencyInput.value = newIdempotencyKey();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hide(formError);
  const payload = readForm();
  if (payload.error) {
    show(formError, payload.error);
    return;
  }

  localStorage.setItem(apiKeyStorage, payload.apiKey);
  submitButton.disabled = true;
  submitButton.textContent = "Отправляем…";
  try {
    const response = await fetch("/api/v1/payments", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": payload.apiKey,
        "Idempotency-Key": payload.idempotencyKey,
      },
      body: JSON.stringify(payload.body),
    });
    const data = await readJson(response);
    if (!response.ok) {
      show(formError, errorText(response.status, data));
      return;
    }
    remember({
      id: data.payment_id,
      status: data.status,
      amount: payload.body.amount,
      currency: payload.body.currency,
    });
    renderAccepted(data);
    await pollPayment(data.payment_id, payload.apiKey);
    idempotencyInput.value = newIdempotencyKey();
  } catch (error) {
    show(formError, "Не удалось связаться с API");
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Создать платёж";
  }
});

lookupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hide(lookupError);
  const paymentId = document.querySelector("#lookup-id").value.trim();
  if (!paymentId) {
    show(lookupError, "Укажите идентификатор");
    return;
  }
  try {
    await loadPayment(paymentId, apiKeyInput.value.trim());
  } catch (error) {
    show(lookupError, error.message);
  }
});

historyList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-id]");
  if (!button) return;
  hide(lookupError);
  try {
    await loadPayment(button.dataset.id, apiKeyInput.value.trim());
  } catch (error) {
    show(lookupError, error.message);
  }
});

function readForm() {
  let metadata = {};
  const rawMetadata = document.querySelector("#metadata").value.trim();
  if (rawMetadata) {
    try {
      metadata = JSON.parse(rawMetadata);
    } catch {
      return { error: "Метаданные должны быть JSON-объектом" };
    }
    if (metadata === null || Array.isArray(metadata) || typeof metadata !== "object") {
      return { error: "Метаданные должны быть JSON-объектом" };
    }
  }
  return {
    apiKey: apiKeyInput.value.trim(),
    idempotencyKey: idempotencyInput.value.trim(),
    body: {
      amount: document.querySelector("#amount").value.trim(),
      currency: document.querySelector("#currency").value,
      description: document.querySelector("#description").value.trim(),
      metadata,
      webhook_url: document.querySelector("#webhook").value.trim(),
    },
  };
}

async function loadPayment(paymentId, apiKey) {
  const response = await fetch(`/api/v1/payments/${encodeURIComponent(paymentId)}`, {
    headers: { "X-API-Key": apiKey },
  });
  const data = await readJson(response);
  if (!response.ok) {
    throw new Error(errorText(response.status, data));
  }
  renderPayment(data);
  remember(data);
  if (data.status === "pending") {
    await pollPayment(data.id, apiKey);
  }
}

async function pollPayment(paymentId, apiKey) {
  const token = ++pollToken;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await delay(1000);
    if (token !== pollToken) return;
    const response = await fetch(`/api/v1/payments/${paymentId}`, {
      headers: { "X-API-Key": apiKey },
    });
    if (!response.ok) return;
    const payment = await response.json();
    if (token !== pollToken) return;
    renderPayment(payment);
    remember(payment);
    if (payment.status !== "pending") return;
  }
}

function renderAccepted(payment) {
  card.className = "card";
  card.innerHTML = `
    <div class="status-row">
      <strong class="amount">Платёж принят</strong>
      ${badge(payment.status)}
    </div>
    <p class="meta">Ждём ответ шлюза</p>
    <dl>
      <dt>payment_id</dt><dd>${escapeHtml(payment.payment_id)}</dd>
      <dt>created_at</dt><dd>${escapeHtml(formatTime(payment.created_at))}</dd>
    </dl>
  `;
}

function renderPayment(payment) {
  card.className = "card";
  const waiting = payment.status === "pending" ? "<p class=\"meta\">Ждём ответ шлюза</p>" : "";
  card.innerHTML = `
    <div class="status-row">
      <strong class="amount">${escapeHtml(payment.amount)} ${escapeHtml(payment.currency)}</strong>
      ${badge(payment.status)}
    </div>
    ${waiting}
    <dl>
      <dt>id</dt><dd>${escapeHtml(payment.id)}</dd>
      <dt>описание</dt><dd>${escapeHtml(payment.description)}</dd>
      <dt>idempotency</dt><dd>${escapeHtml(payment.idempotency_key)}</dd>
      <dt>webhook</dt><dd>${escapeHtml(payment.webhook_url)}</dd>
      <dt>created_at</dt><dd>${escapeHtml(formatTime(payment.created_at))}</dd>
      <dt>processed_at</dt><dd>${escapeHtml(payment.processed_at ? formatTime(payment.processed_at) : "—")}</dd>
      <dt>metadata</dt><dd>${escapeHtml(JSON.stringify(payment.metadata))}</dd>
    </dl>
  `;
}

function badge(status) {
  return `<span class="badge ${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function remember(payment) {
  const id = payment.id || payment.payment_id;
  const items = loadHistory().filter((item) => item.id !== id);
  items.unshift({
    id,
    status: payment.status,
    amount: payment.amount || "",
    currency: payment.currency || "",
  });
  sessionStorage.setItem(historyKey, JSON.stringify(items.slice(0, 8)));
  renderHistory();
}

function renderHistory() {
  const items = loadHistory();
  if (!items.length) {
    historyList.innerHTML = "<li class=\"meta\">Пока пусто</li>";
    return;
  }
  historyList.innerHTML = items
    .map(
      (item) => `
        <li>
          <button type="button" data-id="${escapeHtml(item.id)}">
            ${escapeHtml(item.amount)} ${escapeHtml(item.currency)} · ${escapeHtml(item.status)}
            <br />${escapeHtml(item.id)}
          </button>
        </li>
      `,
    )
    .join("");
}

function loadHistory() {
  try {
    return JSON.parse(sessionStorage.getItem(historyKey) || "[]");
  } catch {
    return [];
  }
}

function errorText(status, data) {
  if (status === 401) return "Неверный API-ключ";
  if (status === 404) return "Платёж не найден";
  if (data && typeof data.detail === "string") return data.detail;
  if (data && Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg).filter(Boolean).join("; ") || "Проверьте поля формы";
  }
  return "Запрос отклонён";
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function newIdempotencyKey() {
  return `pay-${crypto.randomUUID()}`;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU");
}

function show(node, message) {
  node.hidden = false;
  node.textContent = message;
}

function hide(node) {
  node.hidden = true;
  node.textContent = "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
