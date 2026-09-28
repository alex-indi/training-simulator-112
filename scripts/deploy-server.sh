#!/usr/bin/env bash

set -Eeuo pipefail

REPO_DIR="/home/alex/projects/training-simulator-112"
SERVICE="training-simulator-112"
BACKEND_URL="http://127.0.0.1:8112"

# uv установлен для пользователя alex.
export PATH="$HOME/.local/bin:$PATH"

# Не допускаем двух deploy одновременно.
exec 9>/tmp/training-simulator-112-deploy.lock

if ! flock -n 9; then
    echo "ERROR: другой deploy уже выполняется"
    exit 1
fi

TARGET_SHA="${1:-}"

if [ -z "$TARGET_SHA" ]; then
    echo "ERROR: не передан SHA коммита"
    exit 1
fi

cd "$REPO_DIR"

PREVIOUS_SHA="$(git rev-parse HEAD)"

echo "========================================"
echo "Training Simulator 112 deployment"
echo "Previous: $PREVIOUS_SHA"
echo "Target:   $TARGET_SHA"
echo "========================================"

echo
echo "=== 1. Fetch repository ==="

git fetch origin main

# Проверяем, что GitHub действительно прислал существующий commit.
git cat-file -e "${TARGET_SHA}^{commit}"

echo
echo "=== 2. Checkout tested commit ==="

git checkout main
git reset --hard "$TARGET_SHA"

echo
echo "=== 3. Backend dependencies ==="

cd "$REPO_DIR/backend"

uv sync --frozen --no-dev

echo
echo "=== 4. Frontend dependencies ==="

cd "$REPO_DIR/frontend"

# GitHub Actions SSH — non-interactive shell, поэтому nvm
# необходимо загрузить явно.
export NVM_DIR="$HOME/.nvm"

if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1091
    source "$NVM_DIR/nvm.sh"
fi

nvm use 22

npm ci

echo
echo "=== 5. Build frontend ==="

# Production работает через same-origin.
VITE_API_URL= npm run build

# Nginx www-data должен видеть новый build.
setfacl -R -m u:www-data:rX "$REPO_DIR/frontend/dist"
setfacl -m d:u:www-data:rX "$REPO_DIR/frontend/dist"

echo
echo "=== 6. Database migrations ==="

cd "$REPO_DIR/backend"

./.venv/bin/alembic upgrade head

echo
echo "=== 7. Reload systemd configuration ==="

sudo -n systemctl daemon-reload

echo
echo "=== 8. Restart backend ==="

sudo -n systemctl restart "$SERVICE"

echo
echo "=== 9. Backend health check ==="

for attempt in {1..30}; do
    if curl -fsS "$BACKEND_URL/health" >/dev/null; then
        echo "Backend is healthy"
        break
    fi

    if [ "$attempt" -eq 30 ]; then
        echo "ERROR: backend health check failed"
        sudo -n systemctl status "$SERVICE" --no-pager || true
        exit 1
    fi

    sleep 1
done

echo
echo "=== 10. Public health check ==="

curl -fsS https://112.rzd-learning.ru/health >/dev/null

echo
echo "========================================"
echo "DEPLOY SUCCESSFUL"
echo "$PREVIOUS_SHA -> $TARGET_SHA"
echo "https://112.rzd-learning.ru"
echo "========================================"
