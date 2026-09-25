"""REST API готовых карточек происшествий."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

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
from app.modules.training.clock import active_seconds
from app.modules.training.models import (
    QueueMode,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
    training_session_trainees,
)
from app.realtime import publish_session_event

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
        order_number=action.order_number,
        comment=action.comment,
        created_at=action.created_at,
    )


def _to_read_model(incident: Incident, user: User) -> IncidentRead:
    member_run = next(
        (run for run in incident.training_session.runs if run.trainee_id == user.id), None
    )
    is_shared = incident.training_group_id is not None
    if user.role == UserRole.TRAINEE:
        context_run = member_run
    elif is_shared:
        context_run = next(
            (
                run
                for run in incident.training_session.runs
                if run.id == incident.claimed_by_training_run_id
            ),
            None,
        ) or next(
            (
                run
                for run in incident.training_session.runs
                if run.group_id == incident.training_group_id
            ),
            None,
        )
    else:
        context_run = incident.training_run
    can_act = (
        user.role == UserRole.TRAINEE
        and incident.training_session.state == TrainingSessionState.ACTIVE
        and not incident.training_session.paused_at
        and not (member_run and member_run.paused_at)
        and (
            incident.claimed_by_training_run_id == member_run.id
            if is_shared and member_run is not None
            else not is_shared
            and (incident.training_run is None or incident.training_run.trainee_id == user.id)
        )
    )
    claimant = next(
        (
            run
            for run in incident.training_session.runs
            if run.id == incident.claimed_by_training_run_id
        ),
        None,
    )
    return IncidentRead(
        id=incident.id,
        training_session_id=incident.training_session_id,
        training_run_id=incident.training_run_id,
        training_group_id=incident.training_group_id,
        claimed_by_training_run_id=incident.claimed_by_training_run_id,
        claimed_at=incident.claimed_at,
        claimant_name=claimant.trainee.full_name if claimant else None,
        claimant_workstation_number=claimant.workstation_number if claimant else None,
        can_claim=bool(
            is_shared
            and member_run
            and member_run.group_id == incident.training_group_id
            and member_run.queue_mode == QueueMode.SHARED_QUEUE
            and incident.claimed_by_training_run_id is None
            and incident.training_session.state == TrainingSessionState.ACTIVE
            and not incident.training_session.finish_mode
            and not incident.training_session.paused_at
            and not member_run.paused_at
        ),
        can_edit=can_act,
        viewer_dds_profile=context_run.dds_profile if context_run else None,
        viewer_workstation_number=context_run.workstation_number if context_run else None,
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
        available_actions=get_available_actions(incident) if can_act and incident.opened_at else [],
        actions=[_to_action_read_model(action) for action in incident.actions],
        scenario_events=[
            {
                "id": event.id,
                "kind": event.kind,
                "body": event.body,
                "origin": event.origin,
                "created_at": event.created_at,
            }
            for event in (incident.scenario_events or [])
        ],
        created_at=incident.created_at,
        delivered_at=incident.delivered_at,
        opened_at=incident.opened_at,
        primary_status_at=incident.primary_status_at,
        primary_response_duration_seconds=(
            active_seconds(
                incident.delivered_at,
                incident.primary_status_at,
                incident.training_session.pauses,
                context_run.pauses if context_run else [],
            )
            if incident.primary_status_at is not None and incident.delivered_at is not None
            else None
        ),
        finished_at=incident.finished_at,
    )


def _ensure_incident_visible(incident: Incident, user: User) -> None:
    session = incident.training_session
    is_owner = user.role == UserRole.INSTRUCTOR and session.instructor_id == user.id
    if incident.training_group_id is not None:
        is_trainee = user.role == UserRole.TRAINEE and any(
            run.trainee_id == user.id
            and run.group_id == incident.training_group_id
            and run.queue_mode == QueueMode.SHARED_QUEUE
            for run in session.runs
        )
    else:
        is_trainee = (
            user.role == UserRole.TRAINEE
            and any(trainee.id == user.id for trainee in session.trainees)
            and (incident.training_run is None or incident.training_run.trainee_id == user.id)
        )
    if user.role != UserRole.ADMIN and not is_owner and not is_trainee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Карточка происшествия не найдена",
        )


def _ensure_training_running(incident: Incident, user: User) -> None:
    session = incident.training_session
    if session.paused_at:
        raise HTTPException(status_code=409, detail="Занятие приостановлено преподавателем")
    run = next((item for item in session.runs if item.trainee_id == user.id), None)
    if run and run.paused_at:
        raise HTTPException(status_code=409, detail="Ваш АРМ приостановлен преподавателем")


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
            selectinload(Incident.training_session).selectinload(TrainingSession.trainees),
            selectinload(Incident.training_session).selectinload(TrainingSession.pauses),
            selectinload(Incident.training_session)
            .selectinload(TrainingSession.runs)
            .selectinload(TrainingRun.trainee),
            selectinload(Incident.training_session)
            .selectinload(TrainingSession.runs)
            .selectinload(TrainingRun.pauses),
            selectinload(Incident.actions),
            selectinload(Incident.scenario_events),
            selectinload(Incident.training_run),
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
        select(TrainingSession)
        .options(selectinload(TrainingSession.runs), selectinload(TrainingSession.groups))
        .where(
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
    if training_session.paused_at or training_session.finish_mode:
        raise HTTPException(status_code=409, detail="Выдача карточек приостановлена")

    matching_runs = [
        run
        for run in training_session.runs
        if payload.trainee_id is None or run.trainee_id == payload.trainee_id
    ]
    if payload.training_group_id is not None and payload.trainee_id is not None:
        raise HTTPException(status_code=422, detail="Укажите группу или обучаемого")
    group = (
        next(
            (group for group in training_session.groups if group.id == payload.training_group_id),
            None,
        )
        if payload.training_group_id is not None
        else None
    )
    if payload.training_group_id is not None and (
        group is None
        or group.queue_mode != QueueMode.SHARED_QUEUE
        or not any(run.group_id == group.id for run in training_session.runs)
    ):
        raise HTTPException(status_code=422, detail="Группа не принадлежит общей очереди занятия")
    if (not group and len(matching_runs) > 1) or (
        payload.trainee_id is not None and not matching_runs
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Укажите обучаемого из текущей учебной сессии",
        )
    if group and all(run.paused_at for run in training_session.runs if run.group_id == group.id):
        raise HTTPException(status_code=409, detail="Все АРМ группы приостановлены")
    if not group and any(run.paused_at for run in matching_runs):
        raise HTTPException(status_code=409, detail="АРМ приостановлен")

    incident = create_delivered_incident(
        training_session_id=training_session.id,
        source_snapshot=payload.source_snapshot.model_dump(mode="json"),
    )
    incident.scenario_events = []
    if group:
        incident.training_group_id = group.id
    elif matching_runs:
        run = matching_runs[0]
        if run.queue_mode == QueueMode.SHARED_QUEUE and run.group_id is not None:
            incident.training_group_id = run.group_id
        else:
            incident.training_run = run
    database.add(incident)
    await database.commit()
    incident.training_session = training_session
    await publish_session_event("incident.delivered", training_session.id, incident.id)
    return _to_read_model(incident, current_user)


@router.get("", response_model=list[IncidentRead])
async def list_incidents(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[IncidentRead]:
    """Возвращает карточки только из доступных пользователю учебных сессий."""
    statement = select(Incident).options(
        selectinload(Incident.training_session).selectinload(TrainingSession.trainees),
        selectinload(Incident.training_session).selectinload(TrainingSession.pauses),
        selectinload(Incident.training_session)
        .selectinload(TrainingSession.runs)
        .selectinload(TrainingRun.trainee),
        selectinload(Incident.training_session)
        .selectinload(TrainingSession.runs)
        .selectinload(TrainingRun.pauses),
        selectinload(Incident.actions),
        selectinload(Incident.scenario_events),
        selectinload(Incident.training_run),
    )
    if current_user.role == UserRole.INSTRUCTOR:
        statement = statement.join(TrainingSession).where(
            TrainingSession.instructor_id == current_user.id
        )
    elif current_user.role == UserRole.TRAINEE:
        member_run = aliased(TrainingRun)
        statement = (
            statement.join(TrainingSession)
            .join(training_session_trainees)
            .outerjoin(TrainingRun, Incident.training_run_id == TrainingRun.id)
            .where(
                training_session_trainees.c.trainee_id == current_user.id,
                or_(
                    and_(
                        Incident.training_group_id.is_(None),
                        or_(
                            Incident.training_run_id.is_(None),
                            TrainingRun.trainee_id == current_user.id,
                        ),
                    ),
                    Incident.training_group_id.in_(
                        select(member_run.group_id)
                        .where(
                            member_run.training_session_id == Incident.training_session_id,
                            member_run.trainee_id == current_user.id,
                            member_run.queue_mode == QueueMode.SHARED_QUEUE,
                        )
                        .correlate(Incident)
                    ),
                ),
            )
        )

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


@router.post("/{incident_id}/claim", response_model=IncidentRead)
async def claim_incident(
    incident_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> IncidentRead:
    """Одна условная запись в БД допускает только одного владельца общей карточки."""
    if current_user.role != UserRole.TRAINEE:
        raise HTTPException(status_code=403, detail="Карточку может взять только обучаемый")
    incident = await _load_incident(database, incident_id)
    _ensure_incident_visible(incident, current_user)
    run = next(
        (run for run in incident.training_session.runs if run.trainee_id == current_user.id), None
    )
    if (
        incident.training_group_id is None
        or run is None
        or run.group_id != incident.training_group_id
        or run.queue_mode != QueueMode.SHARED_QUEUE
    ):
        raise HTTPException(status_code=409, detail="Карточка не входит в вашу общую очередь")
    if incident.training_session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(status_code=409, detail="Занятие не активно")
    if incident.training_session.finish_mode:
        raise HTTPException(status_code=409, detail="Завершение занятия: новые карточки не берутся")
    _ensure_training_running(incident, current_user)
    claimed_at = datetime.now(UTC)
    result = await database.execute(
        update(Incident)
        .where(Incident.id == incident_id, Incident.claimed_by_training_run_id.is_(None))
        .values(
            claimed_by_training_run_id=run.id,
            claimed_at=claimed_at,
            training_run_id=run.id,
        )
        .returning(Incident.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=409, detail="Карточка уже взята в работу другим диспетчером"
        )
    await database.commit()
    database.expire_all()
    updated = await _load_incident(database, incident_id)
    await publish_session_event("incident.claimed", updated.training_session_id, incident_id)
    return _to_read_model(updated, current_user)


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
    if incident.training_session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(
            status_code=409, detail="Открыть карточку можно только в активном занятии"
        )
    _ensure_training_running(incident, current_user)
    if incident.training_group_id is not None and incident.claimed_by_training_run_id != next(
        (run.id for run in incident.training_session.runs if run.trainee_id == current_user.id),
        None,
    ):
        raise HTTPException(status_code=409, detail="Сначала возьмите карточку в работу")
    mark_incident_opened(
        incident,
        actor_user_id=current_user.id,
        actor_display_name=current_user.full_name,
    )
    await database.commit()
    await publish_session_event("incident.opened", incident.training_session_id, incident.id)
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
    _ensure_training_running(incident, current_user)
    if incident.training_group_id is not None and incident.claimed_by_training_run_id != next(
        (run.id for run in incident.training_session.runs if run.trainee_id == current_user.id),
        None,
    ):
        raise HTTPException(
            status_code=409, detail="Карточка уже взята в работу другим диспетчером"
        )
    if incident.training_session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Действия доступны только в активной учебной сессии",
        )
    if incident.opened_at is None:
        raise HTTPException(status_code=409, detail="Сначала откройте карточку")

    try:
        action = perform_incident_action(
            incident,
            action=payload.action,
            actor_user_id=current_user.id,
            actor_display_name=current_user.full_name,
            order_number=payload.order_number,
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
    await publish_session_event("incident.updated", incident.training_session_id, incident.id)
    return _to_read_model(incident, current_user)
