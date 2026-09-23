"""REST API базовой учебной сессии."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.training.models import (
    TrainingSession,
    training_session_trainees,
)
from app.modules.training.schemas import TrainingSessionCreate, TrainingSessionRead
from app.modules.training.workflow import (
    InvalidTrainingSessionTransitionError,
    prepare_training_session,
    start_training_session,
)

router = APIRouter(prefix="/api/training/sessions", tags=["training sessions"])


def _ensure_instructor(user: User) -> None:
    if user.role != UserRole.INSTRUCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Действие доступно только преподавателю",
        )


def _to_read_model(training_session: TrainingSession) -> TrainingSessionRead:
    return TrainingSessionRead(
        id=training_session.id,
        title=training_session.title,
        instructor_id=training_session.instructor_id,
        trainee_ids=[trainee.id for trainee in training_session.trainees],
        state=training_session.state,
        created_at=training_session.created_at,
        started_at=training_session.started_at,
    )


async def _load_session(
    database: AsyncSession,
    training_session_id: int,
    *,
    for_update: bool = False,
) -> TrainingSession:
    statement = (
        select(TrainingSession)
        .where(TrainingSession.id == training_session_id)
        .options(
            selectinload(TrainingSession.trainees),
            selectinload(TrainingSession.runs),
        )
    )
    if for_update:
        statement = statement.with_for_update()

    result = await database.scalars(statement)
    training_session = result.one_or_none()
    if training_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Учебная сессия не найдена",
        )
    return training_session


def _ensure_session_visible(training_session: TrainingSession, user: User) -> None:
    is_owner = (
        user.role == UserRole.INSTRUCTOR
        and training_session.instructor_id == user.id
    )
    is_trainee = user.role == UserRole.TRAINEE and any(
        trainee.id == user.id for trainee in training_session.trainees
    )
    if user.role != UserRole.ADMIN and not is_owner and not is_trainee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Учебная сессия не найдена",
        )


def _ensure_session_owner(training_session: TrainingSession, user: User) -> None:
    _ensure_instructor(user)
    if training_session.instructor_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Учебная сессия не найдена",
        )


@router.post(
    "",
    response_model=TrainingSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_training_session(
    payload: TrainingSessionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    """Создаёт черновик сессии и назначает активных обучаемых."""
    _ensure_instructor(current_user)

    result = await database.scalars(
        select(User).where(
            User.id.in_(payload.trainee_ids),
            User.role == UserRole.TRAINEE,
            User.is_active.is_(True),
        )
    )
    trainees = list(result.all())
    if {trainee.id for trainee in trainees} != set(payload.trainee_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Все назначенные пользователи должны быть активными обучаемыми",
        )

    training_session = TrainingSession(
        title=payload.title,
        instructor_id=current_user.id,
        trainees=trainees,
    )
    database.add(training_session)
    await database.commit()
    return _to_read_model(training_session)


@router.get("", response_model=list[TrainingSessionRead])
async def list_training_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[TrainingSessionRead]:
    """Возвращает сессии, доступные текущей роли."""
    statement = select(TrainingSession).options(
        selectinload(TrainingSession.trainees)
    )
    if current_user.role == UserRole.INSTRUCTOR:
        statement = statement.where(TrainingSession.instructor_id == current_user.id)
    elif current_user.role == UserRole.TRAINEE:
        statement = statement.join(training_session_trainees).where(
            training_session_trainees.c.trainee_id == current_user.id
        )

    result = await database.scalars(statement.order_by(TrainingSession.id.desc()))
    return [_to_read_model(item) for item in result.unique().all()]


@router.get("/{training_session_id}", response_model=TrainingSessionRead)
async def read_training_session(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    """Восстанавливает каноническое состояние сессии из базы данных."""
    training_session = await _load_session(database, training_session_id)
    _ensure_session_visible(training_session, current_user)
    return _to_read_model(training_session)


@router.post("/{training_session_id}/prepare", response_model=TrainingSessionRead)
async def prepare_session(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    """Подготавливает заполненный преподавателем черновик к запуску."""
    training_session = await _load_session(
        database,
        training_session_id,
        for_update=True,
    )
    _ensure_session_owner(training_session, current_user)
    try:
        prepare_training_session(training_session)
    except InvalidTrainingSessionTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    await database.commit()
    return _to_read_model(training_session)


@router.post("/{training_session_id}/start", response_model=TrainingSessionRead)
async def start_session(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    """Запускает подготовленную сессию от имени её преподавателя."""
    training_session = await _load_session(
        database,
        training_session_id,
        for_update=True,
    )
    _ensure_session_owner(training_session, current_user)
    try:
        start_training_session(training_session)
    except InvalidTrainingSessionTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    await database.commit()
    return _to_read_model(training_session)
