"""REST API пользователей локального демонстрационного стенда."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.identity.passwords import verify_password
from app.modules.identity.schemas import (
    UserLogin,
    UserRead,
    WorkstationClaim,
    WorkstationPresenceRead,
)

router = APIRouter(prefix="/api/users", tags=["users"])
WORKSTATION_ONLINE_WINDOW = timedelta(seconds=45)


def _presence(user: User) -> WorkstationPresenceRead:
    return WorkstationPresenceRead(
        user_id=user.id,
        trainee_name=user.full_name,
        workstation_number=user.workstation_number,
        last_seen_at=user.workstation_last_seen_at,
    )


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


@router.get("/workstations", response_model=list[WorkstationPresenceRead])
async def list_online_workstations(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[WorkstationPresenceRead]:
    if current_user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Доступно только преподавателю")
    online_since = datetime.now(UTC) - WORKSTATION_ONLINE_WINDOW
    users = await session.scalars(
        select(User).where(
            User.role == UserRole.TRAINEE,
            User.is_active.is_(True),
            User.workstation_number.is_not(None),
            User.workstation_last_seen_at >= online_since,
        ).order_by(User.workstation_number)
    )
    return [_presence(user) for user in users]


@router.put("/workstation", response_model=WorkstationPresenceRead)
async def claim_workstation(
    payload: WorkstationClaim,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> WorkstationPresenceRead:
    if current_user.role != UserRole.TRAINEE:
        raise HTTPException(status_code=403, detail="АРМ может занять только обучаемый")
    now = datetime.now(UTC)
    occupant = await session.scalar(
        select(User).where(
            User.workstation_number == payload.workstation_number,
            User.id != current_user.id,
        ).with_for_update()
    )
    if occupant is not None:
        if (
            occupant.workstation_last_seen_at
            and now - occupant.workstation_last_seen_at < WORKSTATION_ONLINE_WINDOW
        ):
            raise HTTPException(status_code=409, detail="Рабочее место уже занято")
        occupant.workstation_number = None
        occupant.workstation_last_seen_at = None
        await session.flush()
    current_user.workstation_number = payload.workstation_number
    current_user.workstation_last_seen_at = now
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Рабочее место уже занято") from error
    return _presence(current_user)


@router.post("/workstation/heartbeat", status_code=204)
async def heartbeat_workstation(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> None:
    if current_user.role != UserRole.TRAINEE or current_user.workstation_number is None:
        raise HTTPException(status_code=404, detail="АРМ не занят")
    current_user.workstation_last_seen_at = datetime.now(UTC)
    await session.commit()


@router.delete("/workstation", status_code=204)
async def release_workstation(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> None:
    if current_user.role != UserRole.TRAINEE:
        raise HTTPException(status_code=403, detail="АРМ может освободить только обучаемый")
    current_user.workstation_number = None
    current_user.workstation_last_seen_at = None
    await session.commit()
