#!/usr/bin/env bash
# Развёртывание демо-стенда на чистой Ubuntu 22.04/24.04.
# Запускать из корня проекта: bash scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Docker: официальный установщик, а если он недоступен — пакеты из репозитория Ubuntu
if ! command -v docker >/dev/null 2>&1; then
  echo "→ Устанавливаю Docker"
  if ! curl -fsSL --max-time 60 https://get.docker.com | sudo sh; then
    echo "→ Официальный установщик недоступен, ставлю Docker из репозитория Ubuntu"
    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose-v2
  fi
fi
SUDO=""; docker info >/dev/null 2>&1 || SUDO="sudo"

if ! $SUDO docker compose version >/dev/null 2>&1; then
  echo "✗ Нет Docker Compose v2. Установите: sudo apt-get install -y docker-compose-v2"; exit 1
fi

# 2. Если Docker Hub недоступен (403 или таймаут — бывает у российских облаков), включаем зеркало
# Доступный Docker Hub отвечает 401 (нужен токен); 403 или 000 (таймаут) — значит, закрыт
HUB=$(curl -s --max-time 15 -o /dev/null -w '%{http_code}' https://registry-1.docker.io/v2/ || true)
if [ "$HUB" != "401" ]; then
  if [ ! -f /etc/docker/daemon.json ]; then
    echo "→ Docker Hub недоступен, включаю зеркало mirror.gcr.io"
    echo '{"registry-mirrors": ["https://mirror.gcr.io"]}' | sudo tee /etc/docker/daemon.json >/dev/null
    sudo systemctl restart docker
  fi
fi

# 3. Секреты
if [ ! -f .env ]; then
  echo "→ Создаю .env со случайными секретами"
  cp .env.example .env
  sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 16)/" .env
  sed -i "s/^WORKER_REPLICAS=.*/WORKER_REPLICAS=1/" .env
fi

# 4. Сборка и запуск
echo "→ Собираю и запускаю. Первый раз 5–10 минут, на ВМ с долевым процессором — до часа; не прерывайте"
$SUDO docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

echo "→ Жду готовности"
for i in $(seq 1 120); do
  if curl -fs http://localhost/api/catalog >/dev/null 2>&1; then
    IP=$(curl -fs --max-time 10 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
    echo "✓ Готово: http://$IP"
    echo "  Если адрес внутренний (10.x, 192.168.x) — возьмите публичный IP в консоли облака."
    echo "  Проверка сценария: $SUDO docker compose exec api python -m app.smoke"
    exit 0
  fi
  sleep 5
done
echo "✗ Стенд не ответил за 10 минут. Состояние: $SUDO docker compose ps; логи: $SUDO docker compose logs --tail=100"
exit 1