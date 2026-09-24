"""REST API пользователей локального демонстрационного стенда."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.identity.passwords import verify_password
from app.modules.identity.schemas import UserLogin, UserRead

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("/login", response_model=UserRead)
async def login(
    payload: UserLogin,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> User:
    """Checks a managed password while preserving legacy demo accounts."""
    user = (
        await session.scalars(
            select(User).where(
                User.username == payload.username.strip().lower(),
                User.is_active.is_(True),
            )
        )
    ).one_or_none()
    invalid_password = user is not None and user.password_hash is not None and not verify_password(
        payload.password, user.password_hash
    )
    if user is None or invalid_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )
    return user


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
