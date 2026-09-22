"""FastAPI-зависимости для работы с базой данных."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Выдаёт транзакционную сессию базы данных на время запроса."""
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.database_session_factory
    )
    async with session_factory() as session:
        yield session
