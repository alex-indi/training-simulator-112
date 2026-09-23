"""REST API подготовки занятия и учебного класса."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.training.models import (
    TrainingGroup,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
    TrainingTemplate,
    training_session_trainees,
)
from app.modules.training.schemas import (
    BulkAssignment,
    GroupRead,
    GroupWrite,
    JoinRequest,
    ReadinessRead,
    RunRead,
    SessionSettings,
    TemplateCreate,
    TemplateRead,
    TrainingSessionCreate,
    TrainingSessionRead,
    TrainingSessionUpdate,
)
from app.modules.training.workflow import (
    InvalidTrainingSessionTransitionError,
    prepare_training_session,
    start_training_session,
)

router = APIRouter(prefix="/api/training/sessions", tags=["training sessions"])
template_router = APIRouter(prefix="/api/training/templates", tags=["training templates"])
ONLINE_WINDOW = timedelta(seconds=45)


def _ensure_instructor(user: User) -> None:
    if user.role != UserRole.INSTRUCTOR:
        raise HTTPException(status_code=403, detail="Действие доступно только преподавателю")


def _editable(item: TrainingSession) -> None:
    if item.state not in (TrainingSessionState.DRAFT, TrainingSessionState.READY):
        raise HTTPException(status_code=409, detail="После запуска настройки занятия неизменяемы")


def _readiness(item: TrainingSession) -> ReadinessRead:
    now = datetime.now(UTC)
    runs = item.runs
    online = sum(bool(run.last_seen_at and now - run.last_seen_at < ONLINE_WINDOW) for run in runs)
    assigned = sum(bool(run.dds_profile and run.dds_profile != "ДДС") for run in runs)
    stationed = sum(bool(run.workstation_number) for run in runs)
    warnings = []
    if not runs:
        warnings.append("Нет подключённых участников")
    if assigned != len(runs):
        warnings.append("Назначьте профиль ДДС каждому участнику")
    if len(runs) != len(item.trainees):
        warnings.append("Не все назначенные обучаемые заняли АРМ")
    if stationed != len(runs):
        warnings.append("Назначьте рабочее место каждому участнику")
    if online < len(runs):
        warnings.append(f"Offline: {len(runs) - online}")
    return ReadinessRead(
        participant_count=len(runs),
        workstation_count=item.workstation_count,
        group_count=len(item.groups),
        profiles_assigned=assigned,
        online_count=online,
        offline_count=len(runs) - online,
        warnings=warnings,
        can_start=(
            bool(runs)
            and assigned == len(runs)
            and stationed == len(runs)
            and len(runs) == len(item.trainees)
        ),
    )


def _to_read_model(item: TrainingSession) -> TrainingSessionRead:
    now = datetime.now(UTC)
    return TrainingSessionRead(
        id=item.id,
        title=item.title,
        topic=item.topic or "",
        mode=item.mode,
        duration_minutes=item.duration_minutes,
        delivery_interval_seconds=item.delivery_interval_seconds,
        delivery_order=item.delivery_order,
        workstation_count=item.workstation_count,
        instructor_id=item.instructor_id,
        trainee_ids=[user.id for user in item.trainees],
        state=item.state,
        created_at=item.created_at,
        started_at=item.started_at,
        runs=[
            RunRead(
                id=run.id,
                trainee_id=run.trainee_id,
                trainee_name=run.trainee.full_name,
                workstation_number=run.workstation_number,
                dds_profile=run.dds_profile,
                difficulty=run.difficulty,
                queue_mode=run.queue_mode,
                group_id=run.group_id,
                online=bool(run.last_seen_at and now - run.last_seen_at < ONLINE_WINDOW),
                last_seen_at=run.last_seen_at,
            )
            for run in sorted(item.runs, key=lambda run: run.workstation_number or 0)
        ],
        groups=[
            GroupRead(
                id=group.id,
                name=group.name,
                dds_profile=group.dds_profile,
                difficulty=group.difficulty,
                queue_mode=group.queue_mode,
                run_ids=[run.id for run in item.runs if run.group_id == group.id],
            )
            for group in item.groups
        ],
        readiness=_readiness(item),
    )


async def _load_session(
    database: AsyncSession, training_session_id: int, *, for_update: bool = False
) -> TrainingSession:
    statement = (
        select(TrainingSession)
        .where(TrainingSession.id == training_session_id)
        .options(
            selectinload(TrainingSession.trainees),
            selectinload(TrainingSession.runs).selectinload(TrainingRun.trainee),
            selectinload(TrainingSession.groups),
        )
    )
    if for_update:
        statement = statement.with_for_update(of=TrainingSession)
    item = (await database.scalars(statement)).one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Учебная сессия не найдена")
    return item


def _ensure_session_visible(item: TrainingSession, user: User) -> None:
    if user.role == UserRole.ADMIN or (
        user.role == UserRole.INSTRUCTOR and item.instructor_id == user.id
    ):
        return
    if user.role == UserRole.TRAINEE and any(trainee.id == user.id for trainee in item.trainees):
        return
    raise HTTPException(status_code=404, detail="Учебная сессия не найдена")


def _ensure_session_owner(item: TrainingSession, user: User) -> None:
    _ensure_instructor(user)
    if item.instructor_id != user.id:
        raise HTTPException(status_code=404, detail="Учебная сессия не найдена")


def _apply_settings(item: TrainingSession, payload: SessionSettings) -> None:
    for key in (
        "title",
        "topic",
        "mode",
        "duration_minutes",
        "delivery_interval_seconds",
        "delivery_order",
        "workstation_count",
    ):
        setattr(item, key, getattr(payload, key))


async def _save(database: AsyncSession, item: TrainingSession) -> TrainingSessionRead:
    await database.commit()
    return _to_read_model(await _load_session(database, item.id))


@router.post("", response_model=TrainingSessionRead, status_code=status.HTTP_201_CREATED)
async def create_training_session(
    payload: TrainingSessionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    _ensure_instructor(current_user)
    trainees = (
        list(
            (
                await database.scalars(
                    select(User).where(
                        User.id.in_(payload.trainee_ids),
                        User.role == UserRole.TRAINEE,
                        User.is_active.is_(True),
                    )
                )
            ).all()
        )
        if payload.trainee_ids
        else []
    )
    if {trainee.id for trainee in trainees} != set(payload.trainee_ids):
        raise HTTPException(
            status_code=422, detail="Все назначенные пользователи должны быть активными обучаемыми"
        )
    item = TrainingSession(instructor_id=current_user.id, trainees=trainees)
    _apply_settings(item, payload)
    database.add(item)
    return await _save(database, item)


@router.get("", response_model=list[TrainingSessionRead])
async def list_training_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[TrainingSessionRead]:
    statement = select(TrainingSession).options(
        selectinload(TrainingSession.trainees),
        selectinload(TrainingSession.runs).selectinload(TrainingRun.trainee),
        selectinload(TrainingSession.groups),
    )
    if current_user.role == UserRole.INSTRUCTOR:
        statement = statement.where(TrainingSession.instructor_id == current_user.id)
    elif current_user.role == UserRole.TRAINEE:
        statement = statement.outerjoin(training_session_trainees).where(
            or_(
                TrainingSession.state.in_((TrainingSessionState.DRAFT, TrainingSessionState.READY)),
                training_session_trainees.c.trainee_id == current_user.id,
            )
        )
    result = await database.scalars(statement.order_by(TrainingSession.id.desc()))
    return [_to_read_model(item) for item in result.unique().all()]


@router.get("/{training_session_id}", response_model=TrainingSessionRead)
async def read_training_session(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id)
    _ensure_session_visible(item, current_user)
    return _to_read_model(item)


@router.put("/{training_session_id}", response_model=TrainingSessionRead)
async def update_training_session(
    training_session_id: int,
    payload: TrainingSessionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    _editable(item)
    if any(
        run.workstation_number and run.workstation_number > payload.workstation_count
        for run in item.runs
    ):
        raise HTTPException(status_code=409, detail="Номер занятого АРМ превышает размер класса")
    _apply_settings(item, payload)
    if item.state == TrainingSessionState.READY:
        item.state = TrainingSessionState.DRAFT
    return await _save(database, item)


@router.post("/{training_session_id}/join", response_model=TrainingSessionRead)
async def join_training_session(
    training_session_id: int,
    payload: JoinRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    if current_user.role != UserRole.TRAINEE:
        raise HTTPException(status_code=403, detail="АРМ может занять только обучаемый")
    item = await _load_session(database, training_session_id, for_update=True)
    if item.state not in (
        TrainingSessionState.DRAFT,
        TrainingSessionState.READY,
        TrainingSessionState.ACTIVE,
    ):
        raise HTTPException(status_code=409, detail="Занятие недоступно для подключения")
    if payload.workstation_number > item.workstation_count:
        raise HTTPException(status_code=422, detail="Номер АРМ вне учебного класса")
    existing = next((run for run in item.runs if run.trainee_id == current_user.id), None)
    if item.state == TrainingSessionState.ACTIVE and existing is None:
        raise HTTPException(status_code=409, detail="После запуска новые участники не добавляются")
    if (
        existing
        and item.state == TrainingSessionState.ACTIVE
        and existing.workstation_number != payload.workstation_number
    ):
        raise HTTPException(status_code=409, detail="После запуска номер АРМ неизменяем")
    if any(
        run.workstation_number == payload.workstation_number and run.trainee_id != current_user.id
        for run in item.runs
    ):
        raise HTTPException(status_code=409, detail="Рабочее место уже занято")
    if existing is None:
        existing = TrainingRun(
            trainee_id=current_user.id, workstation_number=payload.workstation_number
        )
        item.runs.append(existing)
        if not any(trainee.id == current_user.id for trainee in item.trainees):
            item.trainees.append(current_user)
    else:
        existing.workstation_number = payload.workstation_number
    existing.last_seen_at = datetime.now(UTC)
    try:
        return await _save(database, item)
    except IntegrityError as error:
        await database.rollback()
        raise HTTPException(status_code=409, detail="Рабочее место уже занято") from error


@router.post("/{training_session_id}/heartbeat", response_model=TrainingSessionRead)
async def heartbeat(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id)
    run = next((run for run in item.runs if run.trainee_id == current_user.id), None)
    if current_user.role != UserRole.TRAINEE or run is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    run.last_seen_at = datetime.now(UTC)
    return await _save(database, item)


@router.post("/{training_session_id}/groups", response_model=TrainingSessionRead)
async def create_group(
    training_session_id: int,
    payload: GroupWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    _editable(item)
    if any(group.name == payload.name for group in item.groups):
        raise HTTPException(status_code=409, detail="Группа с таким названием уже существует")
    item.groups.append(TrainingGroup(**payload.model_dump()))
    return await _save(database, item)


@router.put("/{training_session_id}/groups/{group_id}", response_model=TrainingSessionRead)
async def update_group(
    training_session_id: int,
    group_id: int,
    payload: GroupWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    _editable(item)
    group = next((group for group in item.groups if group.id == group_id), None)
    if group is None:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    if any(other.name == payload.name and other.id != group_id for other in item.groups):
        raise HTTPException(status_code=409, detail="Группа с таким названием уже существует")
    for key, value in payload.model_dump().items():
        setattr(group, key, value)
    for run in item.runs:
        if run.group_id == group_id:
            run.dds_profile = group.dds_profile or "ДДС"
            run.difficulty = group.difficulty
            run.queue_mode = group.queue_mode
    return await _save(database, item)


@router.delete("/{training_session_id}/groups/{group_id}", response_model=TrainingSessionRead)
async def delete_group(
    training_session_id: int,
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    _editable(item)
    group = next((group for group in item.groups if group.id == group_id), None)
    if group is None:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    for run in item.runs:
        if run.group_id == group_id:
            run.group_id = None
    item.groups.remove(group)
    return await _save(database, item)


@router.post("/{training_session_id}/assign", response_model=TrainingSessionRead)
async def assign_runs(
    training_session_id: int,
    payload: BulkAssignment,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    _editable(item)
    if len(set(payload.run_ids)) != len(payload.run_ids):
        raise HTTPException(status_code=422, detail="Участники не должны повторяться")
    targets = [run for run in item.runs if run.id in payload.run_ids]
    if len(targets) != len(payload.run_ids):
        raise HTTPException(status_code=422, detail="Участник не найден в занятии")
    if payload.group_id is not None and not any(
        group.id == payload.group_id for group in item.groups
    ):
        raise HTTPException(status_code=422, detail="Группа не найдена в занятии")
    if not any(
        key in payload.model_fields_set
        for key in ("dds_profile", "difficulty", "queue_mode", "group_id")
    ):
        raise HTTPException(status_code=422, detail="Укажите назначаемые параметры")
    for run in targets:
        if payload.group_id is not None:
            group = next(group for group in item.groups if group.id == payload.group_id)
            run.dds_profile = group.dds_profile or "ДДС"
            run.difficulty = group.difficulty
            run.queue_mode = group.queue_mode
        for key in ("dds_profile", "difficulty", "queue_mode", "group_id"):
            if key in payload.model_fields_set:
                setattr(run, key, getattr(payload, key))
    return await _save(database, item)


@router.post("/{training_session_id}/prepare", response_model=TrainingSessionRead)
async def prepare_session(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    if not _readiness(item).can_start:
        raise HTTPException(status_code=409, detail="Подключите участников и назначьте профиль ДДС")
    try:
        prepare_training_session(item)
    except InvalidTrainingSessionTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return await _save(database, item)


@router.post("/{training_session_id}/start", response_model=TrainingSessionRead)
async def start_session(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    if not _readiness(item).can_start:
        raise HTTPException(status_code=409, detail="Подключите участников и назначьте профиль ДДС")
    try:
        start_training_session(item)
    except InvalidTrainingSessionTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return await _save(database, item)


@template_router.post("", response_model=TemplateRead, status_code=201)
async def save_template(
    payload: TemplateCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TemplateRead:
    item = await _load_session(database, payload.training_session_id)
    _ensure_session_owner(item, current_user)
    settings = SessionSettings.model_validate(item, from_attributes=True).model_dump(mode="json")
    settings["groups"] = [
        GroupWrite.model_validate(group, from_attributes=True).model_dump(mode="json")
        for group in item.groups
    ]
    template = TrainingTemplate(
        instructor_id=current_user.id, name=payload.name.strip(), settings=settings
    )
    database.add(template)
    await database.commit()
    return TemplateRead.model_validate(template, from_attributes=True)


@template_router.get("", response_model=list[TemplateRead])
async def list_templates(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[TemplateRead]:
    _ensure_instructor(current_user)
    templates = (
        await database.scalars(
            select(TrainingTemplate)
            .where(TrainingTemplate.instructor_id == current_user.id)
            .order_by(TrainingTemplate.id.desc())
        )
    ).all()
    return [TemplateRead.model_validate(template, from_attributes=True) for template in templates]


@template_router.post(
    "/{template_id}/sessions", response_model=TrainingSessionRead, status_code=201
)
async def create_from_template(
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    _ensure_instructor(current_user)
    template = (
        await database.scalars(
            select(TrainingTemplate).where(
                TrainingTemplate.id == template_id,
                TrainingTemplate.instructor_id == current_user.id,
            )
        )
    ).one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    settings = SessionSettings.model_validate(
        {key: value for key, value in template.settings.items() if key != "groups"}
    )
    item = TrainingSession(instructor_id=current_user.id)
    _apply_settings(item, settings)
    item.groups = [
        TrainingGroup(**GroupWrite.model_validate(group).model_dump())
        for group in template.settings.get("groups", [])
    ]
    database.add(item)
    return await _save(database, item)
