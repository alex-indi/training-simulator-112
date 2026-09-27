#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_root"

docker_ready() {
    command -v docker >/dev/null 2>&1 &&
        docker compose version >/dev/null 2>&1 &&
        docker info >/dev/null 2>&1
}

ask_install_mac() {
    printf 'Для запуска нужны Docker CLI, Compose и среда контейнеров Colima. Установить недостающее через Homebrew? [д/Н]: '
    IFS= read -r answer || answer=
    case "$answer" in
        д|Д|да|ДА|y|Y|yes|YES) ;;
        *) echo "Установка отменена. Файлы и данные стенда не изменены."; exit 1 ;;
    esac
}

ensure_homebrew() {
    if command -v brew >/dev/null 2>&1; then return; fi
    echo "Устанавливаю Homebrew с официального сайта..."
    (
        installer=$(mktemp "${TMPDIR:-/tmp}/ut112-homebrew.XXXXXX")
        trap 'rm -f "$installer"' EXIT
        curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$installer"
        NONINTERACTIVE=1 /bin/bash "$installer"
    )
    for brew_dir in /opt/homebrew/bin /usr/local/bin; do
        if [ -x "$brew_dir/brew" ]; then
            PATH="$brew_dir:$PATH"
            export PATH
            return
        fi
    done
    echo "Homebrew установлен, но команда brew недоступна. Откройте новый терминал и повторите запуск." >&2
    exit 1
}

install_missing_mac_tools() {
    set --
    if ! command -v docker >/dev/null 2>&1; then set -- "$@" docker; fi
    if ! docker compose version >/dev/null 2>&1; then set -- "$@" docker-compose; fi
    if ! docker buildx version >/dev/null 2>&1; then set -- "$@" docker-buildx; fi
    if ! docker info >/dev/null 2>&1 && [ ! -d /Applications/Docker.app ] && ! command -v colima >/dev/null 2>&1; then
        set -- "$@" colima
    fi
    if [ "$#" -gt 0 ]; then brew install "$@"; fi
    plugin_dir="$HOME/.docker/cli-plugins"
    brew_prefix=$(brew --prefix)
    mkdir -p "$plugin_dir"
    for plugin in docker-compose docker-buildx; do
        if [ ! -e "$plugin_dir/$plugin" ] && [ ! -L "$plugin_dir/$plugin" ] &&
            [ -x "$brew_prefix/opt/$plugin/bin/$plugin" ]; then
            ln -s "$brew_prefix/opt/$plugin/bin/$plugin" "$plugin_dir/$plugin"
        fi
    done
}

if [ "$(uname -s)" = Darwin ]; then
    if [ -d /Applications/Docker.app ]; then
        PATH="/Applications/Docker.app/Contents/Resources/bin:$HOME/.docker/bin:$PATH"
        export PATH
    fi
    if ! docker_ready; then
        if [ -d /Applications/Docker.app ] &&
            command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
            echo "Запускаю Docker Desktop..."
            open -a Docker >/dev/null 2>&1 || true
        else
            ask_install_mac
            ensure_homebrew
            install_missing_mac_tools
        fi
    fi
    if ! docker info >/dev/null 2>&1 && command -v colima >/dev/null 2>&1 &&
        [ ! -d /Applications/Docker.app ]; then
        echo "Запускаю Colima..."
        colima start --runtime docker
    fi
    attempt=0
    while ! docker_ready && [ "$attempt" -lt 60 ]; do
        sleep 2
        attempt=$((attempt + 1))
    done
fi
if ! docker_ready; then
    echo "Docker Engine и Compose недоступны. Проверьте запуск Colima или Docker Desktop и повторите попытку." >&2
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
