"""REST API виртуальных групп и их назначений."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import DDSResponseStatus, Incident
from app.modules.incidents.router import _ensure_incident_visible, _load_incident
from app.modules.response.models import ResponseAssignment, ResponseUnit
from app.modules.response.schemas import (
    ResponseAssignmentCreate,
    ResponseAssignmentEventRead,
    ResponseAssignmentRead,
    ResponseScenarioEventCreate,
    ResponseUnitCreate,
    ResponseUnitRead,
)
from app.modules.response.workflow import (
    InvalidResponseTransitionError,
    apply_scenario_event,
    create_assignment,
)
from app.modules.training.models import TrainingRun, TrainingSession, TrainingSessionState

router = APIRouter(prefix="/api/response", tags=["response"])


def _unit_read(unit: ResponseUnit) -> ResponseUnitRead:
    return ResponseUnitRead(
        id=unit.id,
        name=unit.name,
        dds_profile=unit.dds_profile,
        description=unit.description,
        is_active=unit.is_active,
    )


def _assignment_read(assignment: ResponseAssignment) -> ResponseAssignmentRead:
    return ResponseAssignmentRead(
        id=assignment.id,
        incident_id=assignment.incident_id,
        response_unit=_unit_read(assignment.response_unit),
        training_run_id=assignment.training_run_id,
        state=assignment.state,
        assigned_at=assignment.assigned_at,
        state_changed_at=assignment.state_changed_at,
        events=[
            ResponseAssignmentEventRead(
                id=event.id,
                from_state=event.from_state,
                to_state=event.to_state,
                event_key=event.event_key,
                actor_user_id=event.actor_user_id,
                created_at=event.created_at,
            )
            for event in assignment.events
        ],
    )


def _assignment_options():
    return (
        selectinload(ResponseAssignment.response_unit),
        selectinload(ResponseAssignment.events),
        selectinload(ResponseAssignment.incident)
        .selectinload(Incident.training_session)
        .selectinload(TrainingSession.trainees),
        selectinload(ResponseAssignment.incident).selectinload(Incident.training_run),
    )


@router.post("/units", response_model=ResponseUnitRead, status_code=status.HTTP_201_CREATED)
async def create_response_unit(
    payload: ResponseUnitCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> ResponseUnitRead:
    """Преподаватель добавляет повторно используемую виртуальную группу."""
    if current_user.role not in {UserRole.INSTRUCTOR, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Создавать группы может только преподаватель")
    unit = ResponseUnit(**payload.model_dump(), is_active=True)
    database.add(unit)
    await database.commit()
    return _unit_read(unit)


@router.get("/units", response_model=list[ResponseUnitRead])
async def list_response_units(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
    incident_id: int | None = None,
) -> list[ResponseUnitRead]:
    """Показывает только активные группы, доступные профилю обучаемого."""
    statement = select(ResponseUnit).where(ResponseUnit.is_active.is_(True))
    if incident_id is not None:
        incident = await _load_incident(database, incident_id)
        _ensure_incident_visible(incident, current_user)
        if incident.training_run is None:
            return []
        statement = statement.where(
            ResponseUnit.dds_profile == incident.training_run.dds_profile
        )
    elif current_user.role == UserRole.TRAINEE:
        active_profiles = select(TrainingRun.dds_profile).join(TrainingSession).where(
            TrainingRun.trainee_id == current_user.id,
            TrainingSession.state == TrainingSessionState.ACTIVE,
        )
        statement = statement.where(ResponseUnit.dds_profile.in_(active_profiles))
    result = await database.scalars(statement.order_by(ResponseUnit.name, ResponseUnit.id))
    return [_unit_read(unit) for unit in result.all()]


@router.post(
    "/incidents/{incident_id}/assignments",
    response_model=ResponseAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_response_unit(
    incident_id: int,
    payload: ResponseAssignmentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> ResponseAssignmentRead:
    """Назначает доступную группу на принятую обучаемым карточку."""
    if current_user.role != UserRole.TRAINEE:
        raise HTTPException(status_code=403, detail="Назначать группу может только обучаемый")
    incident = await _load_incident(database, incident_id, for_update=True)
    _ensure_incident_visible(incident, current_user)
    if incident.training_run is None or incident.training_run.trainee_id != current_user.id:
        raise HTTPException(status_code=409, detail="Карточка не привязана к вашему TrainingRun")
    if incident.training_session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(status_code=409, detail="Учебная сессия не активна")
    if incident.dds_status not in {
        DDSResponseStatus.ACCEPTED,
        DDSResponseStatus.RESPONSE_STARTED,
        DDSResponseStatus.ARRIVED,
        DDSResponseStatus.WORKING,
    }:
        raise HTTPException(status_code=409, detail="Сначала примите карточку")

    result = await database.scalars(
        select(ResponseUnit).where(
            ResponseUnit.id == payload.response_unit_id,
            ResponseUnit.is_active.is_(True),
            ResponseUnit.dds_profile == incident.training_run.dds_profile,
        )
    )
    unit = result.one_or_none()
    if unit is None:
        raise HTTPException(status_code=422, detail="Группа недоступна для профиля ДДС")
    existing = await database.scalar(
        select(ResponseAssignment.id).where(
            ResponseAssignment.incident_id == incident.id,
            ResponseAssignment.response_unit_id == unit.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Группа уже назначена на эту карточку")

    assignment = create_assignment(
        incident_id=incident.id,
        training_run_id=incident.training_run_id,
        response_unit=unit,
        actor_user_id=current_user.id,
    )
    database.add(assignment)
    await database.commit()
    return _assignment_read(assignment)


@router.get(
    "/incidents/{incident_id}/assignments", response_model=list[ResponseAssignmentRead]
)
async def list_response_assignments(
    incident_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[ResponseAssignmentRead]:
    """Восстанавливает текущее состояние и историю из БД после reload."""
    incident = await _load_incident(database, incident_id)
    _ensure_incident_visible(incident, current_user)
    result = await database.scalars(
        select(ResponseAssignment)
        .where(ResponseAssignment.incident_id == incident_id)
        .options(*_assignment_options())
        .order_by(ResponseAssignment.id)
    )
    return [_assignment_read(item) for item in result.all()]


@router.post(
    "/assignments/{assignment_id}/scenario-events",
    response_model=ResponseAssignmentRead,
)
async def apply_response_scenario_event(
    assignment_id: int,
    payload: ResponseScenarioEventCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> ResponseAssignmentRead:
    """Применяет детерминированное событие сценария серверным временем."""
    if current_user.role not in {UserRole.INSTRUCTOR, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="События сценария доступны преподавателю")
    result = await database.scalars(
        select(ResponseAssignment)
        .where(ResponseAssignment.id == assignment_id)
        .options(*_assignment_options())
        .with_for_update()
    )
    assignment = result.one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Назначение группы не найдено")
    session = assignment.incident.training_session
    if current_user.role != UserRole.ADMIN and session.instructor_id != current_user.id:
        raise HTTPException(status_code=404, detail="Назначение группы не найдено")
    if session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(status_code=409, detail="Учебная сессия не активна")
    try:
        apply_scenario_event(
            assignment,
            target_state=payload.target_state,
            event_key=payload.event_key,
        )
    except InvalidResponseTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await database.commit()
    return _assignment_read(assignment)
