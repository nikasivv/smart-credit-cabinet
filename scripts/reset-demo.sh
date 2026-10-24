#!/usr/bin/env bash
# Сбросить данные стенда к исходным демо-данным (перед показом жюри).
set -euo pipefail
cd "$(dirname "$0")/.."
SUDO=""; docker info >/dev/null 2>&1 || SUDO="sudo"
F="-f docker-compose.yml -f docker-compose.prod.yml"
$SUDO docker compose $F down -v
$SUDO docker compose $F up -d
echo "Данные сброшены. Стенд поднимется примерно через минуту."
