"""Окружение Alembic для асинхронного PostgreSQL engine."""

from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = get_settings().database_url.replace("%", "%%")
config.set_main_option("sqlalchemy.url", database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Формирует SQL миграций без подключения к базе данных."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_sync_migrations(connection: Connection) -> None:
    """Выполняет миграции через синхронный адаптер Alembic."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Подключается к PostgreSQL и применяет миграции."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(run_sync_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_migrations_online())
