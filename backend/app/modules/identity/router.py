"""REST API пользователей локального демонстрационного стенда."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.identity.schemas import UserRead

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/demo", response_model=list[UserRead])
async def list_demo_users(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[User]:
    """Возвращает активных пользователей для переключателя локального стенда."""
    result = await session.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.id)
    )
    return list(result.all())


@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Возвращает пользователя и роль текущего локального запроса."""
    return current_user
