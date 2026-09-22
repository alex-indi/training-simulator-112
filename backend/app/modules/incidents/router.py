"""REST API готовых карточек происшествий."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import Incident, IncidentAction
from app.modules.incidents.schemas import (
    IncidentActionCreate,
    IncidentActionRead,
    IncidentCreate,
    IncidentRead,
)
from app.modules.incidents.workflow import (
    IncidentActionCommentRequiredError,
    InvalidIncidentTransitionError,
    create_delivered_incident,
    get_available_actions,
    mark_incident_opened,
    perform_incident_action,
)
from app.modules.training.models import (
    TrainingSession,
    TrainingSessionState,
    training_session_trainees,
)

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def _to_action_read_model(action: IncidentAction) -> IncidentActionRead:
    return IncidentActionRead(
        id=action.id,
        actor_user_id=action.actor_user_id,
        actor_display_name=action.actor_display_name,
        is_system=action.is_system,
        status=action.status,
        action=action.action,
        from_status=action.from_status,
        to_status=action.to_status,
        comment=action.comment,
        created_at=action.created_at,
    )


def _to_read_model(incident: Incident, user: User) -> IncidentRead:
    can_act = (
        user.role == UserRole.TRAINEE
        and incident.training_session.state == TrainingSessionState.ACTIVE
    )
    return IncidentRead(
        id=incident.id,
        training_session_id=incident.training_session_id,
        incident_number=incident.incident_number,
        reported_at=incident.reported_at,
        source=incident.source,
        applicant_name=incident.applicant_name,
        applicant_phone=incident.applicant_phone,
        address=incident.address,
        latitude=incident.latitude,
        longitude=incident.longitude,
        description=incident.description,
        incident_type=incident.incident_type,
        source_snapshot=incident.source_snapshot,
        lifecycle_state=incident.lifecycle_state,
        dds_status=incident.dds_status,
        available_actions=get_available_actions(incident) if can_act else [],
        actions=[_to_action_read_model(action) for action in incident.actions],
        created_at=incident.created_at,
        delivered_at=incident.delivered_at,
        opened_at=incident.opened_at,
        primary_status_at=incident.primary_status_at,
        primary_response_duration_seconds=(
            (incident.primary_status_at - incident.delivered_at).total_seconds()
            if incident.primary_status_at is not None and incident.delivered_at is not None
            else None
        ),
        finished_at=incident.finished_at,
    )


def _ensure_incident_visible(incident: Incident, user: User) -> None:
    session = incident.training_session
    is_owner = user.role == UserRole.INSTRUCTOR and session.instructor_id == user.id
    is_trainee = user.role == UserRole.TRAINEE and any(
        trainee.id == user.id for trainee in session.trainees
    )
    if user.role != UserRole.ADMIN and not is_owner and not is_trainee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Карточка происшествия не найдена",
        )


async def _load_incident(
    database: AsyncSession,
    incident_id: int,
    *,
    for_update: bool = False,
) -> Incident:
    statement = (
        select(Incident)
        .where(Incident.id == incident_id)
        .options(
            selectinload(Incident.training_session).selectinload(
                TrainingSession.trainees
            ),
            selectinload(Incident.actions),
        )
    )
    if for_update:
        statement = statement.with_for_update()

    result = await database.scalars(statement)
    incident = result.one_or_none()
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Карточка происшествия не найдена",
        )
    return incident


@router.post("", response_model=IncidentRead, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> IncidentRead:
    """Копирует подготовленные данные Virtual112 и доставляет карточку в сессию."""
    if current_user.role != UserRole.INSTRUCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доставлять карточки может только преподаватель",
        )

    result = await database.scalars(
        select(TrainingSession).where(
            TrainingSession.id == payload.training_session_id,
            TrainingSession.instructor_id == current_user.id,
        )
    )
    training_session = result.one_or_none()
    if training_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Учебная сессия не найдена",
        )
    if training_session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Карточку можно доставить только в активную учебную сессию",
        )

    incident = create_delivered_incident(
        training_session_id=training_session.id,
        source_snapshot=payload.source_snapshot.model_dump(mode="json"),
    )
    database.add(incident)
    await database.commit()
    incident.training_session = training_session
    return _to_read_model(incident, current_user)


@router.get("", response_model=list[IncidentRead])
async def list_incidents(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[IncidentRead]:
    """Возвращает карточки только из доступных пользователю учебных сессий."""
    statement = select(Incident).options(
        selectinload(Incident.training_session).selectinload(TrainingSession.trainees),
        selectinload(Incident.actions),
    )
    if current_user.role == UserRole.INSTRUCTOR:
        statement = statement.join(TrainingSession).where(
            TrainingSession.instructor_id == current_user.id
        )
    elif current_user.role == UserRole.TRAINEE:
        statement = statement.join(TrainingSession).join(
            training_session_trainees
        ).where(training_session_trainees.c.trainee_id == current_user.id)

    result = await database.scalars(statement.order_by(Incident.id.desc()))
    return [_to_read_model(item, current_user) for item in result.unique().all()]


@router.get("/{incident_id}", response_model=IncidentRead)
async def read_incident(
    incident_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> IncidentRead:
    """Восстанавливает карточку и её исходный snapshot из PostgreSQL."""
    incident = await _load_incident(database, incident_id)
    _ensure_incident_visible(incident, current_user)
    return _to_read_model(incident, current_user)


@router.post("/{incident_id}/open", response_model=IncidentRead)
async def open_incident(
    incident_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> IncidentRead:
    """Фиксирует первое открытие карточки назначенным обучаемым."""
    if current_user.role != UserRole.TRAINEE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Открытие карточки фиксируется только для обучаемого",
        )

    incident = await _load_incident(database, incident_id, for_update=True)
    _ensure_incident_visible(incident, current_user)
    mark_incident_opened(
        incident,
        actor_user_id=current_user.id,
        actor_display_name=current_user.full_name,
    )
    await database.commit()
    return _to_read_model(incident, current_user)


@router.post("/{incident_id}/actions", response_model=IncidentRead)
async def change_incident_status(
    incident_id: int,
    payload: IncidentActionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> IncidentRead:
    """Выполняет разрешённое действие ДДС и сохраняет его серверное время."""
    if current_user.role != UserRole.TRAINEE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Статус ДДС может менять только обучаемый",
        )

    incident = await _load_incident(database, incident_id, for_update=True)
    _ensure_incident_visible(incident, current_user)
    if incident.training_session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Действия доступны только в активной учебной сессии",
        )

    try:
        action = perform_incident_action(
            incident,
            action=payload.action,
            actor_user_id=current_user.id,
            actor_display_name=current_user.full_name,
            comment=payload.comment,
        )
    except IncidentActionCommentRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except InvalidIncidentTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    database.add(action)
    await database.commit()
    return _to_read_model(incident, current_user)
