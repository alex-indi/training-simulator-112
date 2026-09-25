"""REST API виртуальных групп и их назначений."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import DDSResponseStatus, Incident
from app.modules.incidents.router import _ensure_incident_visible, _load_incident
from app.modules.response.models import (
    ResponseAssignment,
    ResponseMessage,
    ResponseMessageSender,
    ResponseUnit,
)
from app.modules.response.realtime import notify_message_created
from app.modules.response.schemas import (
    ResponseAssignmentCreate,
    ResponseAssignmentEventRead,
    ResponseAssignmentRead,
    ResponseMessageCreate,
    ResponseMessageRead,
    ResponseScenarioEventCreate,
    ResponseScenarioMessageCreate,
    ResponseUnitCreate,
    ResponseUnitRead,
)
from app.modules.response.workflow import (
    STATE_REPORTS,
    InvalidResponseTransitionError,
    apply_scenario_event,
    create_assignment,
    create_message,
)
from app.modules.training.models import TrainingRun, TrainingSession, TrainingSessionState
from app.realtime import publish_session_event

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
        dispatch_service_id=assignment.dispatch_service_id,
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
        selectinload(ResponseAssignment.training_run),
        selectinload(ResponseAssignment.events),
        selectinload(ResponseAssignment.messages),
        selectinload(ResponseAssignment.incident)
        .selectinload(Incident.training_session)
        .selectinload(TrainingSession.trainees),
        selectinload(ResponseAssignment.incident)
        .selectinload(Incident.training_session)
        .selectinload(TrainingSession.runs),
        selectinload(ResponseAssignment.incident).selectinload(Incident.training_run),
    )


def _message_read(message: ResponseMessage) -> ResponseMessageRead:
    return ResponseMessageRead(
        id=message.id,
        response_assignment_id=message.response_assignment_id,
        sender_type=message.sender_type,
        body=message.body,
        actor_user_id=message.actor_user_id,
        created_at=message.created_at,
        read_at=message.read_at,
    )


async def _load_visible_assignment(
    database: AsyncSession, assignment_id: int, user: User, *, for_update: bool = False
) -> ResponseAssignment:
    statement = (
        select(ResponseAssignment)
        .where(ResponseAssignment.id == assignment_id)
        .options(*_assignment_options())
    )
    if for_update:
        statement = statement.with_for_update()
    assignment = await database.scalar(statement)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Назначение группы не найдено")
    _ensure_incident_visible(assignment.incident, user)
    return assignment


def _ensure_owner(assignment: ResponseAssignment, user: User) -> None:
    if user.role != UserRole.TRAINEE or assignment.training_run.trainee_id != user.id:
        raise HTTPException(
            status_code=403, detail="Канал доступен только обучаемому этой карточки"
        )


def _ensure_owner_active(assignment: ResponseAssignment, user: User) -> None:
    _ensure_owner(assignment, user)
    if assignment.incident.training_session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(status_code=409, detail="Учебная сессия не активна")
    if assignment.incident.training_session.paused_at or assignment.training_run.paused_at:
        raise HTTPException(status_code=409, detail="Работа приостановлена преподавателем")


def _ensure_instructor(assignment: ResponseAssignment, user: User) -> None:
    if user.role not in {UserRole.INSTRUCTOR, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Сценарное сообщение доступно преподавателю")
    if (
        user.role != UserRole.ADMIN
        and assignment.incident.training_session.instructor_id != user.id
    ):
        raise HTTPException(status_code=404, detail="Назначение группы не найдено")
    if assignment.incident.training_session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(status_code=409, detail="Учебная сессия не активна")
    if assignment.incident.training_session.paused_at or assignment.training_run.paused_at:
        raise HTTPException(status_code=409, detail="Работа приостановлена преподавателем")


@router.get("/assignments/{assignment_id}/messages", response_model=list[ResponseMessageRead])
async def list_response_messages(
    assignment_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[ResponseMessageRead]:
    assignment = await _load_visible_assignment(database, assignment_id, current_user)
    return [_message_read(message) for message in assignment.messages]


@router.post(
    "/assignments/{assignment_id}/messages",
    response_model=ResponseMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def send_response_message(
    assignment_id: int,
    payload: ResponseMessageCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> ResponseMessageRead:
    assignment = await _load_visible_assignment(database, assignment_id, current_user)
    _ensure_owner_active(assignment, current_user)
    message = create_message(
        assignment,
        sender_type=ResponseMessageSender.DISPATCHER,
        body=payload.body,
        actor_user_id=current_user.id,
    )
    await database.commit()
    await notify_message_created(message, current_user.id, assignment.incident.training_session_id)
    return _message_read(message)


@router.post("/assignments/{assignment_id}/request-state", response_model=list[ResponseMessageRead])
async def request_response_state(
    assignment_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[ResponseMessageRead]:
    assignment = await _load_visible_assignment(
        database, assignment_id, current_user, for_update=True
    )
    _ensure_owner_active(assignment, current_user)
    question = create_message(
        assignment,
        sender_type=ResponseMessageSender.DISPATCHER,
        body="Запросить состояние группы",
        actor_user_id=current_user.id,
    )
    answer = create_message(
        assignment,
        sender_type=ResponseMessageSender.RESPONSE_UNIT,
        body=STATE_REPORTS[assignment.state],
    )
    await database.commit()
    await notify_message_created(answer, current_user.id, assignment.incident.training_session_id)
    return [_message_read(question), _message_read(answer)]


@router.post(
    "/assignments/{assignment_id}/scenario-messages",
    response_model=ResponseMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def send_scenario_message(
    assignment_id: int,
    payload: ResponseScenarioMessageCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> ResponseMessageRead:
    assignment = await _load_visible_assignment(
        database, assignment_id, current_user, for_update=True
    )
    _ensure_instructor(assignment, current_user)
    existing = next(
        (item for item in assignment.messages if item.event_key == payload.event_key), None
    )
    try:
        message = create_message(
            assignment,
            sender_type=ResponseMessageSender.RESPONSE_UNIT,
            body=payload.body,
            event_key=payload.event_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if existing is None:
        await database.commit()
        await notify_message_created(
            message, assignment.training_run.trainee_id, assignment.incident.training_session_id
        )
    return _message_read(message)


@router.post("/messages/{message_id}/read", response_model=ResponseMessageRead)
async def mark_response_message_read(
    message_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> ResponseMessageRead:
    message = await database.scalar(select(ResponseMessage).where(ResponseMessage.id == message_id))
    if message is None:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    assignment = await _load_visible_assignment(
        database, message.response_assignment_id, current_user
    )
    _ensure_owner(assignment, current_user)
    if message.sender_type == ResponseMessageSender.RESPONSE_UNIT and message.read_at is None:
        message.read_at = datetime.now(UTC)
        await database.commit()
    return _message_read(message)


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
        statement = statement.where(ResponseUnit.dds_profile == incident.training_run.dds_profile)
    elif current_user.role == UserRole.TRAINEE:
        active_profiles = (
            select(TrainingRun.dds_profile)
            .join(TrainingSession)
            .where(
                TrainingRun.trainee_id == current_user.id,
                TrainingSession.state == TrainingSessionState.ACTIVE,
            )
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

    if incident.scenario_instance_id is not None:
        available_services = {
            service.get("service_id")
            for service in incident.source_snapshot.get("scenario_services", [])
        }
        if payload.dispatch_service_id not in available_services:
            raise HTTPException(status_code=422, detail="Выберите службу из сценария")
    elif payload.dispatch_service_id is not None:
        raise HTTPException(status_code=422, detail="Служба доступна только для сценарной карточки")
    if payload.dispatch_service_id is not None:
        service_assignment = await database.scalar(
            select(ResponseAssignment.id).where(
                ResponseAssignment.incident_id == incident.id,
                ResponseAssignment.dispatch_service_id == payload.dispatch_service_id,
            )
        )
        if service_assignment is not None:
            raise HTTPException(status_code=409, detail="Службе уже назначена группа")

    assignment = create_assignment(
        incident_id=incident.id,
        training_run_id=incident.training_run_id,
        response_unit=unit,
        actor_user_id=current_user.id,
    )
    assignment.dispatch_service_id = payload.dispatch_service_id
    database.add(assignment)
    try:
        await database.commit()
    except IntegrityError as error:
        await database.rollback()
        raise HTTPException(
            status_code=409, detail="Группа уже назначена на эту карточку"
        ) from error
    await publish_session_event(
        "response.assignment_created", incident.training_session_id, incident.id
    )
    return _assignment_read(assignment)


@router.get("/incidents/{incident_id}/assignments", response_model=list[ResponseAssignmentRead])
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
    if session.paused_at or assignment.training_run.paused_at:
        raise HTTPException(status_code=409, detail="Работа приостановлена преподавателем")
    try:
        event = apply_scenario_event(
            assignment,
            target_state=payload.target_state,
            event_key=payload.event_key,
        )
    except InvalidResponseTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    message_key = f"state:{payload.event_key}"
    existing_message = next(
        (item for item in assignment.messages if item.event_key == message_key), None
    )
    message = create_message(
        assignment,
        sender_type=ResponseMessageSender.RESPONSE_UNIT,
        body=STATE_REPORTS[event.to_state],
        event_key=message_key,
        server_time=event.created_at,
    )
    await database.commit()
    await publish_session_event(
        "response.state_changed",
        assignment.incident.training_session_id,
        assignment.incident_id,
    )
    if existing_message is None:
        await notify_message_created(
            message, assignment.training_run.trainee_id, assignment.incident.training_session_id
        )
    return _assignment_read(assignment)
