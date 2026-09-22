"""REST API готовых карточек происшествий."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import Incident
from app.modules.incidents.schemas import IncidentCreate, IncidentRead
from app.modules.incidents.workflow import create_delivered_incident
from app.modules.training.models import (
    TrainingSession,
    TrainingSessionState,
    training_session_trainees,
)

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def _to_read_model(incident: Incident) -> IncidentRead:
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
        created_at=incident.created_at,
        delivered_at=incident.delivered_at,
        opened_at=incident.opened_at,
        primary_status_at=incident.primary_status_at,
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


async def _load_incident(database: AsyncSession, incident_id: int) -> Incident:
    result = await database.scalars(
        select(Incident)
        .where(Incident.id == incident_id)
        .options(
            selectinload(Incident.training_session).selectinload(
                TrainingSession.trainees
            )
        )
    )
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
    return _to_read_model(incident)


@router.get("", response_model=list[IncidentRead])
async def list_incidents(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[IncidentRead]:
    """Возвращает карточки только из доступных пользователю учебных сессий."""
    statement = select(Incident).options(
        selectinload(Incident.training_session).selectinload(TrainingSession.trainees)
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
    return [_to_read_model(item) for item in result.unique().all()]


@router.get("/{incident_id}", response_model=IncidentRead)
async def read_incident(
    incident_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> IncidentRead:
    """Восстанавливает карточку и её исходный snapshot из PostgreSQL."""
    incident = await _load_incident(database, incident_id)
    _ensure_incident_visible(incident, current_user)
    return _to_read_model(incident)
