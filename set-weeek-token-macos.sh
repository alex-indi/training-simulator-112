#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Файл '$ENV_FILE' не найден."
  echo "Запустите скрипт из корня проекта или передайте путь:"
  echo "  ./set-weeek-token-macos.sh /path/to/.env"
  exit 1
fi

TOKEN="$(grep -E '^[[:space:]]*WEEEK_API_TOKEN[[:space:]]*=' "$ENV_FILE" | head -n 1 | sed -E 's/^[[:space:]]*WEEEK_API_TOKEN[[:space:]]*=[[:space:]]*//')"

# Снимаем одинарные/двойные кавычки вокруг значения.
if [[ "$TOKEN" =~ ^\".*\"$ ]] || [[ "$TOKEN" =~ ^\'.*\'$ ]]; then
  TOKEN="${TOKEN:1:${#TOKEN}-2}"
fi

if [[ -z "$TOKEN" ]]; then
  echo "WEEEK_API_TOKEN в '$ENV_FILE' не найден или пустой."
  exit 1
fi

CONFIG_DIR="$HOME/.config/ut112"
TOKEN_FILE="$CONFIG_DIR/weeek_api_token"
ZSHRC="$HOME/.zshrc"
ZPROFILE="$HOME/.zprofile"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST="$LAUNCH_AGENTS/com.ut112.weeek-env.plist"

BEGIN_MARKER="# >>> UT112 WEEEK_API_TOKEN >>>"
END_MARKER="# <<< UT112 WEEEK_API_TOKEN <<<"

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

# Копируем только значение токена в защищённый локальный файл.
printf '%s' "$TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

update_profile() {
  local profile="$1"
  touch "$profile"

  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { skip=1; next }
    $0 == end   { skip=0; next }
    !skip       { print }
  ' "$profile" > "${profile}.ut112.tmp"

  cat >> "${profile}.ut112.tmp" <<'EOF'

# >>> UT112 WEEEK_API_TOKEN >>>
if [ -f "$HOME/.config/ut112/weeek_api_token" ]; then
  export WEEEK_API_TOKEN="$(cat "$HOME/.config/ut112/weeek_api_token")"
fi
# <<< UT112 WEEEK_API_TOKEN <<<
EOF

  mv "${profile}.ut112.tmp" "$profile"
}

update_profile "$ZSHRC"
update_profile "$ZPROFILE"

# Текущая GUI-сессия macOS.
launchctl setenv WEEEK_API_TOKEN "$TOKEN" || true

# Восстанавливаем переменную после каждого входа в macOS.
mkdir -p "$LAUNCH_AGENTS"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ut112.weeek-env</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>/bin/launchctl setenv WEEEK_API_TOKEN "\$(cat '$TOKEN_FILE')"</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
EOF

chmod 600 "$PLIST"

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true

export WEEEK_API_TOKEN="$TOKEN"

echo
echo "OK: WEEEK_API_TOKEN прочитан из $ENV_FILE."
echo "Он сохранён в $TOKEN_FILE и будет восстанавливаться после входа в macOS."
echo "Полностью перезапустите Codex."
echo
echo 'Проверка:'
echo '  test -n "$WEEEK_API_TOKEN" && echo "OK: token is set" || echo "NOT SET"'
