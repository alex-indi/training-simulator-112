# Миграции базы данных

Alembic использует `DATABASE_URL` из корневого `.env` или окружения.

Применить все миграции:

```bash
uv run alembic upgrade head
```

Создать миграцию после изменения SQLAlchemy-моделей:

```bash
uv run alembic revision --autogenerate -m "описание изменения"
```
