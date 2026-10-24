#!/usr/bin/env bash
# Развёртывание демо-стенда на чистой Ubuntu 22.04/24.04.
# Запускать из корня проекта: bash scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "→ Устанавливаю Docker"
  curl -fsSL https://get.docker.com | sudo sh
fi
SUDO=""; docker info >/dev/null 2>&1 || SUDO="sudo"

if [ ! -f .env ]; then
  echo "→ Создаю .env со случайными секретами"
  cp .env.example .env
  sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 16)/" .env
  sed -i "s/^WORKER_REPLICAS=.*/WORKER_REPLICAS=1/" .env
fi

echo "→ Собираю и запускаю (первый раз 5–10 минут)"
$SUDO docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

echo "→ Жду готовности"
for i in $(seq 1 60); do
  if curl -fs http://localhost/api/catalog >/dev/null 2>&1; then
    IP=$(curl -fs https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
    echo "✓ Готово: http://$IP"
    echo "  Проверка сценария: $SUDO docker compose exec api python -m app.smoke"
    exit 0
  fi
  sleep 5
done
echo "✗ Стенд не ответил за 5 минут. Логи: $SUDO docker compose logs --tail=100"
exit 1
