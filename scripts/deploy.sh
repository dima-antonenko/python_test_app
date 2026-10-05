#!/usr/bin/env bash
# Копирует проект на сервер и запускает docker compose.
# Настройки: deploy.env (см. deploy.env.example) или переменные окружения.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${DEPLOY_ENV:-$ROOT/deploy.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${DEPLOY_HOST:?Задайте DEPLOY_HOST в deploy.env}"
DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/python-test-app}"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"

if [[ -n "${DEPLOY_PASSWORD:-}" ]]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "Для DEPLOY_PASSWORD нужен sshpass. Либо настройте SSH-ключ и уберите пароль." >&2
    exit 1
  fi
  export SSHPASS="$DEPLOY_PASSWORD"
  RSYNC_SSH="sshpass -e ssh ${SSH_OPTS[*]}"
  ssh_cmd() { sshpass -e ssh "${SSH_OPTS[@]}" "$@"; }
else
  RSYNC_SSH="ssh ${SSH_OPTS[*]}"
  ssh_cmd() { ssh "${SSH_OPTS[@]}" "$@"; }
fi

echo "Синхронизация в ${TARGET}:${DEPLOY_PATH}"
ssh_cmd "$TARGET" "mkdir -p '$DEPLOY_PATH'"
rsync -az --delete \
  --exclude .git \
  --exclude .venv \
  --exclude __pycache__ \
  --exclude .env \
  --exclude deploy.env \
  --exclude '*.pyc' \
  -e "$RSYNC_SSH" \
  "$ROOT/" "${TARGET}:${DEPLOY_PATH}/"

echo "Сборка и запуск"
ssh_cmd "$TARGET" "cd '$DEPLOY_PATH' && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build"

echo "Состояние"
ssh_cmd "$TARGET" "cd '$DEPLOY_PATH' && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"

echo "Проверка /health"
ssh_cmd "$TARGET" "curl -fsS http://127.0.0.1:8000/health"
echo
echo "API: http://${DEPLOY_HOST}:8000"
