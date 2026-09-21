# Codex project setup

Этот каталог хранится в Git и одинаков для Windows/macOS.

## 1. Установить uv

WEEEK MCP запускается через `uvx`, поэтому `uv` должен быть доступен в `PATH`.

Проверка:

```bash
uv --version
uvx --version
```

## 2. Настроить WEEEK token локально

Скопировать:

```text
.env.example → .env
```

и указать:

```text
WEEEK_API_TOKEN=...
```

`.env` игнорируется Git.

`weeek-mcp` поддерживает переменные окружения и `.env`. Project config также разрешает forwarding `WEEEK_API_TOKEN`, если он задан на уровне ОС/IDE.

Если IDE не видит новую переменную окружения — полностью перезапустить IDE/Codex.

## 3. Проверить MCP

В Codex TUI:

```text
/mcp
```

WEEEK должен отображаться как активный либо как optional server с понятной ошибкой конфигурации.

Проверить `weeek_whoami`.

Если WEEEK временно недоступен, `$project-resume` всё равно должен работать по Git и task handoff.

## 4. Trust

Project-level `.codex/config.toml` применяется в доверенном проекте. Если Codex сообщает, что project config пропущен из-за trust level, пометь локальный clone как trusted через поддерживаемый интерфейс Codex/IDE.

## 5. Почему список WEEEK tools ограничен

Разрешены чтение задач и необходимые изменения статуса/исполнителя.

Не разрешены:

- `weeek_delete_task`;
- `weeek_complete_task`;
- workspace admin CRUD;
- удаление комментариев/базы знаний.

`Done` остаётся человеческим финальным решением.

## 6. На каждом устройстве

Локально отличаются только:

- `.env` / OS secrets;
- установленные runtimes;
- Codex authentication.

Всё остальное приходит через Git.
