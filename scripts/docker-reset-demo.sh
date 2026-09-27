#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

if [ ! -f .env.docker ]; then
    echo "Сначала создайте .env.docker из .env.docker.example." >&2
    exit 1
fi

echo "ВНИМАНИЕ: будут удалены все данные занятий, результаты и PostgreSQL volume."
printf 'Для полного сброса введите RESET: '
read -r confirmation
if [ "$confirmation" != RESET ]; then
    echo "Сброс отменён."
    exit 1
fi

docker compose --env-file .env.docker down -v
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker run --rm backend python -m app.scripts.bootstrap_demo
echo "Демонстрационный стенд создан заново."
