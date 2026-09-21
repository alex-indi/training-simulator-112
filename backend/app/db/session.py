"""Создание SQLAlchemy engine и проверка подключения к PostgreSQL."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Создаёт асинхронный engine для настроенной базы данных."""
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создаёт фабрику транзакционных асинхронных сессий."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database_connection(engine: AsyncEngine) -> None:
    """Проверяет соединение с базой простым запросом."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
