#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_root"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "Установите Docker Desktop (или Docker Engine с Compose) и запустите файл снова." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1 && [ "$(uname -s)" = Darwin ]; then
    echo "Запускаю Docker Desktop..."
    open -a Docker >/dev/null 2>&1 || true
    attempt=0
    while ! docker info >/dev/null 2>&1 && [ "$attempt" -lt 60 ]; do
        sleep 2
        attempt=$((attempt + 1))
    done
fi
if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon недоступен. Запустите Docker Desktop и повторите попытку." >&2
    exit 1
fi

if [ ! -f .env.docker ]; then
    umask 077
    password=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    temp_env=$(mktemp "$project_root/.env.docker.XXXXXX")
    trap 'rm -f "$temp_env"' EXIT
    sed "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$password/" .env.docker.example > "$temp_env"
    mv "$temp_env" .env.docker
    trap - EXIT
    echo "Создан .env.docker с автоматически сгенерированным паролем базы."
fi

docker compose --env-file .env.docker up -d --build --wait --wait-timeout 300

demo_check="SELECT EXISTS (SELECT 1 FROM users WHERE username = 'admin') AND EXISTS (SELECT 1 FROM scenario_templates) AND EXISTS (SELECT 1 FROM city_objects) AND EXISTS (SELECT 1 FROM dispatch_services);"
demo_ready=$(printf '%s\n' "$demo_check" |
    docker compose --env-file .env.docker exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At')
if [ "$demo_ready" != t ]; then
    echo "Наполняю чистую базу демонстрационными данными..."
    docker compose --env-file .env.docker run --rm backend python -m app.scripts.bootstrap_demo
else
    echo "Демонстрационные данные уже есть; повторное наполнение не требуется."
fi

app_port=$(sed -n 's/^APP_PORT=//p' .env.docker | tail -n 1 | tr -d '\r')
app_port=${app_port:-8080}
app_url="http://localhost:$app_port"
echo "Стенд готов: $app_url"
if [ "$(uname -s)" = Darwin ] && [ -z "${CI:-}" ]; then
    open "$app_url" >/dev/null 2>&1 || true
fi
