"""FastAPI-зависимости текущего пользователя локального стенда."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_database_session
from app.modules.identity.models import User

DEFAULT_DEMO_USERNAME = "trainee"


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    demo_username: Annotated[str | None, Header(alias="X-Demo-User")] = None,
) -> User:
    """Определяет активного demo-пользователя по локальному заголовку."""
    username = (demo_username or DEFAULT_DEMO_USERNAME).strip().lower()
    result = await session.scalars(
        select(User).where(User.username == username, User.is_active.is_(True))
    )
    user = result.one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Демонстрационный пользователь не найден",
        )

    return user
