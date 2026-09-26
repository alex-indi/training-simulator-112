"""REST API подготовки занятия и учебного класса."""

import math
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.admin.models import UserGroup
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.scenario_library.instance_models import ScenarioInstance
from app.modules.training.models import (
    QueueMode,
    ScenarioQueueItem,
    TrainingGroup,
    TrainingMode,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
    TrainingSubgroupMember,
    TrainingTemplate,
)
from app.modules.training.schemas import (
    BulkAssignment,
    GroupMemberRead,
    GroupRead,
    GroupWrite,
    JoinRequest,
    OwnRunSummary,
    ReadinessRead,
    RunRead,
    SessionSettings,
    SubgroupWrite,
    TemplateCreate,
    TemplateRead,
    TrainingSessionCreate,
    TrainingSessionRead,
    TrainingSessionSummary,
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


def _invalidate_readiness(item: TrainingSession) -> None:
    if item.state == TrainingSessionState.READY:
        item.state = TrainingSessionState.DRAFT


def _staffed_groups(item: TrainingSession) -> list[TrainingGroup]:
    subgroup_user_ids = {
        membership.user_id
        for group in item.groups
        if group.is_subgroup
        for membership in group.subgroup_memberships
    }
    return [
        group
        for group in item.groups
        if (
            bool(group.subgroup_memberships)
            if group.is_subgroup
            else any(
                user.role == UserRole.TRAINEE and user.id not in subgroup_user_ids
                for user in (group.source_group.members if group.source_group else [])
            )
        )
    ]


def _readiness(item: TrainingSession) -> ReadinessRead:
    now = datetime.now(UTC)
    runs = item.runs
    online = sum(bool(run.last_seen_at and now - run.last_seen_at < ONLINE_WINDOW) for run in runs)
    assigned = sum(bool(run.dds_profile and run.dds_profile != "ДДС") for run in runs)
    stationed = sum(bool(run.workstation_number) for run in runs)
    warnings = []
    if any(group.source_user_group_id is not None for group in item.groups):
        staffed_groups = _staffed_groups(item)
        staffed_group_ids = {group.id for group in staffed_groups}
        masters = [
            row for row in item.master_instances if row.training_group_id in staffed_group_ids
        ]
        assigned_runs = [run for run in runs if run.group_id is not None]
        unassigned = len(runs) - len(assigned_runs)
        required = (
            math.ceil(item.duration_minutes * 60 / item.delivery_interval_seconds)
            if item.mode == TrainingMode.FLOW
            and item.duration_minutes
            and item.delivery_interval_seconds
            else 1
        )
        if not runs:
            warnings.append("Нет подключённых участников")
        if unassigned:
            warnings.append(f"Не распределены: {unassigned}; карточки им не выдаются")
        if online < len(runs):
            warnings.append(f"Offline: {len(runs) - online}")
        for group in staffed_groups:
            cards = [row for row in masters if row.training_group_id == group.id]
            if len(cards) < required:
                warnings.append(f"Группа «{group.name}»: нужно не менее {required} карточек")
            elif any(row.status != "CONFIRMED" for row in cards):
                warnings.append(f"Группа «{group.name}»: набор не утверждён")
        prepared = len(masters)
        approved = sum(row.status == "CONFIRMED" for row in masters)
        return ReadinessRead(
            participant_count=len(runs),
            workstation_count=item.workstation_count,
            group_count=len(staffed_groups),
            profiles_assigned=len(assigned_runs),
            online_count=online,
            offline_count=len(runs) - online,
            warnings=warnings,
            can_start=bool(assigned_runs)
            and bool(staffed_groups)
            and all(
                sum(row.training_group_id == group.id for row in masters) >= required
                for group in staffed_groups
            )
            and prepared == approved,
            prepared_count=prepared,
            approved_count=approved,
        )
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
    prepared = len(item.queue_items)
    approved = sum(queue_item.approved for queue_item in item.queue_items)
    required_per_run = (
        math.ceil(item.duration_minutes * 60 / item.delivery_interval_seconds)
        if item.mode == TrainingMode.FLOW
        and item.duration_minutes
        and item.delivery_interval_seconds
        else 0
    )
    target_count = (
        required_per_run
        if item.mode == TrainingMode.FLOW
        else (1 if item.mode == TrainingMode.FIXED_SET else 0)
    )
    targets = {
        ("group", run.group_id) if run.queue_mode == QueueMode.SHARED_QUEUE else ("run", run.id)
        for run in runs
    }
    pool_complete = all(
        sum(
            queue_item.approved
            and (
                queue_item.training_group_id == target_id
                if target_type == "group"
                else queue_item.training_run_id == target_id
            )
            for queue_item in item.queue_items
        )
        >= target_count
        for target_type, target_id in targets
    )
    shared_runs = [run for run in runs if run.queue_mode == QueueMode.SHARED_QUEUE]
    invalid_shared = any(
        run.group_id is None
        or not any(
            group.id == run.group_id and group.queue_mode == QueueMode.SHARED_QUEUE
            for group in item.groups
        )
        for run in shared_runs
    )
    if item.mode != TrainingMode.MANUAL and not prepared:
        warnings.append("Подготовьте пул карточек")
    if not pool_complete:
        if item.mode == TrainingMode.FLOW:
            warnings.append(
                f"Для FLOW нужно не менее {required_per_run} карточек на каждую очередь"
            )
        else:
            warnings.append("Для FIXED_SET нужна утверждённая карточка для каждой очереди")
    if prepared != approved:
        warnings.append("Утвердите подготовленные карточки")
    if invalid_shared:
        warnings.append("Назначьте общей очереди учебную группу")
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
            and (item.mode == TrainingMode.MANUAL or bool(prepared))
            and pool_complete
            and prepared == approved
            and not invalid_shared
        ),
        prepared_count=prepared,
        approved_count=approved,
    )


def _to_read_model(item: TrainingSession) -> TrainingSessionRead:
    now = datetime.now(UTC)
    subgroup_user_ids = {
        membership.user_id
        for group in item.groups
        if group.is_subgroup
        for membership in group.subgroup_memberships
    }
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
        is_archived=bool(item.is_archived),
        created_at=item.created_at,
        started_at=item.started_at,
        paused_at=item.paused_at,
        paused_seconds=item.paused_seconds or 0,
        finish_mode=item.finish_mode,
        completed_at=item.completed_at,
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
                paused_at=run.paused_at,
            )
            for run in sorted(item.runs, key=lambda run: run.workstation_number or 0)
        ],
        groups=[
            GroupRead(
                id=group.id,
                name=group.name,
                source_user_group_id=group.source_user_group_id,
                dds_profile=group.dds_profile,
                difficulty=group.difficulty,
                queue_mode=group.queue_mode,
                run_ids=[run.id for run in item.runs if run.group_id == group.id],
                is_subgroup=bool(group.is_subgroup),
                members=[
                    GroupMemberRead(id=user.id, full_name=user.full_name)
                    for user in (
                        sorted(
                            (membership.user for membership in group.subgroup_memberships),
                            key=lambda user: (user.full_name, user.id),
                        )
                        if group.is_subgroup
                        else sorted(
                            (
                                user
                                for user in (
                                    group.source_group.members if group.source_group else []
                                )
                                if user.role == UserRole.TRAINEE
                                and user.id not in subgroup_user_ids
                            ),
                            key=lambda user: (user.full_name, user.id),
                        )
                    )
                ],
                member_count=(
                    len(group.subgroup_memberships)
                    if group.is_subgroup
                    else sum(
                        user.role == UserRole.TRAINEE and user.id not in subgroup_user_ids
                        for user in (group.source_group.members if group.source_group else [])
                    )
                ),
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
            selectinload(TrainingSession.groups)
            .selectinload(TrainingGroup.source_group)
            .selectinload(UserGroup.members),
            selectinload(TrainingSession.groups)
            .selectinload(TrainingGroup.subgroup_memberships)
            .selectinload(TrainingSubgroupMember.user),
            selectinload(TrainingSession.master_instances).selectinload(ScenarioInstance.events),
            selectinload(TrainingSession.queue_items),
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


@router.get("", response_model=list[TrainingSessionRead | TrainingSessionSummary])
async def list_training_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[TrainingSessionRead | TrainingSessionSummary]:
    if current_user.role == UserRole.TRAINEE:
        own_run = TrainingRun
        statement = (
            select(TrainingSession, own_run)
            .outerjoin(
                own_run,
                and_(
                    own_run.training_session_id == TrainingSession.id,
                    own_run.trainee_id == current_user.id,
                ),
            )
            .where(
                TrainingSession.is_archived.is_(False),
                or_(
                    TrainingSession.state.in_(
                        (TrainingSessionState.DRAFT, TrainingSessionState.READY)
                    ),
                    own_run.id.is_not(None),
                )
            )
            .order_by(TrainingSession.id.desc())
        )
        rows = (await database.execute(statement)).all()
        now = datetime.now(UTC)
        return [
            TrainingSessionSummary(
                id=item.id,
                title=item.title,
                state=item.state,
                workstation_count=item.workstation_count,
                paused_at=item.paused_at,
                is_archived=bool(item.is_archived),
                own_run=OwnRunSummary(
                    id=run.id,
                    workstation_number=run.workstation_number,
                    dds_profile=run.dds_profile,
                    online=bool(run.last_seen_at and now - run.last_seen_at < ONLINE_WINDOW),
                    paused_at=run.paused_at,
                )
                if run
                else None,
            )
            for item, run in rows
        ]
    statement = select(TrainingSession).where(TrainingSession.is_archived.is_(False)).options(
        selectinload(TrainingSession.trainees),
        selectinload(TrainingSession.runs).selectinload(TrainingRun.trainee),
        selectinload(TrainingSession.groups)
        .selectinload(TrainingGroup.source_group)
        .selectinload(UserGroup.members),
        selectinload(TrainingSession.groups)
        .selectinload(TrainingGroup.subgroup_memberships)
        .selectinload(TrainingSubgroupMember.user),
        selectinload(TrainingSession.master_instances).selectinload(ScenarioInstance.events),
        selectinload(TrainingSession.queue_items),
    )
    if current_user.role == UserRole.INSTRUCTOR:
        statement = statement.where(TrainingSession.instructor_id == current_user.id)
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


@router.post("/{training_session_id}/archive", status_code=204)
async def archive_training_session(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> None:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    if item.state == TrainingSessionState.ACTIVE:
        raise HTTPException(status_code=409, detail="Сначала завершите активное занятие")
    item.is_archived = True
    await database.commit()


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
        group = next(
            (
                group
                for group in item.groups
                if group.is_subgroup
                and any(member.user_id == current_user.id for member in group.subgroup_memberships)
            ),
            None,
        ) or next(
            (
                group
                for group in item.groups
                if group.source_user_group_id is not None
                and group.source_user_group_id == current_user.group_id
            ),
            None,
        )
        if group is not None:
            existing.group_id = group.id
            existing.dds_profile = group.dds_profile or "ДДС"
            existing.difficulty = group.difficulty
            existing.queue_mode = group.queue_mode
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


@router.post("/{training_session_id}/heartbeat", status_code=204)
async def heartbeat(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> None:
    if current_user.role != UserRole.TRAINEE:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    result = await database.execute(
        update(TrainingRun)
        .where(
            TrainingRun.training_session_id == training_session_id,
            TrainingRun.trainee_id == current_user.id,
        )
        .values(last_seen_at=datetime.now(UTC))
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    await database.commit()


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
    if payload.source_user_group_id is not None:
        source = await database.get(UserGroup, payload.source_user_group_id)
        if (
            source is None
            or source.is_archived
            or (
                current_user.role != UserRole.ADMIN and source.created_by_user_id != current_user.id
            )
        ):
            raise HTTPException(status_code=404, detail="Постоянная группа не найдена")
        if any(group.source_user_group_id == source.id for group in item.groups):
            raise HTTPException(status_code=409, detail="Группа уже добавлена в занятие")
        payload = payload.model_copy(update={"name": source.name})
    if any(group.name == payload.name for group in item.groups):
        raise HTTPException(status_code=409, detail="Группа с таким названием уже существует")
    item.groups.append(TrainingGroup(**payload.model_dump()))
    _invalidate_readiness(item)
    return await _save(database, item)


async def _validated_subgroup_users(
    database: AsyncSession, item: TrainingSession, user_ids: list[int], group_id: int | None = None
) -> list[User]:
    if len(user_ids) != len(set(user_ids)):
        raise HTTPException(422, "Участник указан дважды")
    selected_sources = {
        group.source_user_group_id
        for group in item.groups
        if group.source_user_group_id is not None
    }
    if not selected_sources:
        raise HTTPException(422, "Сначала выберите постоянные группы для занятия")
    users = list((await database.scalars(select(User).where(User.id.in_(user_ids)))).all())
    if len(users) != len(user_ids) or any(
        user.role != UserRole.TRAINEE or not user.is_active or user.group_id not in selected_sources
        for user in users
    ):
        raise HTTPException(422, "Участник должен состоять в выбранной группе занятия")
    occupied = {
        membership.user_id
        for group in item.groups
        if group.is_subgroup and group.id != group_id
        for membership in group.subgroup_memberships
    }
    if occupied.intersection(user_ids):
        raise HTTPException(409, "Пользователь уже назначен в другую подгруппу этого занятия")
    return users


def _assign_run_to_group(run: TrainingRun, group: TrainingGroup | None) -> None:
    run.group = group
    run.group_id = group.id if group else None
    run.dds_profile = (group.dds_profile or "ДДС") if group else "ДДС"
    run.difficulty = group.difficulty if group else None
    run.queue_mode = group.queue_mode if group else QueueMode.INDIVIDUAL_QUEUE


@router.post("/{training_session_id}/subgroups", response_model=TrainingSessionRead)
async def create_subgroup(
    training_session_id: int,
    payload: SubgroupWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    _editable(item)
    if any(group.name == payload.name for group in item.groups):
        raise HTTPException(409, "Группа с таким названием уже существует")
    users = await _validated_subgroup_users(database, item, payload.member_user_ids)
    group = TrainingGroup(
        name=payload.name,
        is_subgroup=True,
        difficulty=payload.difficulty,
        queue_mode=payload.queue_mode,
        subgroup_memberships=[
            TrainingSubgroupMember(
                training_session_id=item.id,
                user_id=user.id,
                user=user,
            )
            for user in users
        ],
    )
    item.groups.append(group)
    await database.flush()
    for run in item.runs:
        if run.trainee_id in payload.member_user_ids:
            _assign_run_to_group(run, group)
    _invalidate_readiness(item)
    return await _save(database, item)


@router.put("/{training_session_id}/subgroups/{group_id}", response_model=TrainingSessionRead)
async def update_subgroup(
    training_session_id: int,
    group_id: int,
    payload: SubgroupWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> TrainingSessionRead:
    item = await _load_session(database, training_session_id, for_update=True)
    _ensure_session_owner(item, current_user)
    _editable(item)
    group = next(
        (group for group in item.groups if group.id == group_id and group.is_subgroup), None
    )
    if group is None:
        raise HTTPException(404, "Подгруппа не найдена")
    if any(other.id != group_id and other.name == payload.name for other in item.groups):
        raise HTTPException(409, "Группа с таким названием уже существует")
    users = await _validated_subgroup_users(database, item, payload.member_user_ids, group_id)
    old_ids = {member.user_id for member in group.subgroup_memberships}
    new_ids = set(payload.member_user_ids)
    group.name = payload.name
    group.difficulty = payload.difficulty
    group.queue_mode = payload.queue_mode
    group.subgroup_memberships = [
        member for member in group.subgroup_memberships if member.user_id in new_ids
    ] + [
        TrainingSubgroupMember(training_session_id=item.id, user_id=user.id, user=user)
        for user in users
        if user.id not in old_ids
    ]
    sources = {
        source.source_user_group_id: source
        for source in item.groups
        if source.source_user_group_id is not None
    }
    for run in item.runs:
        if run.trainee_id in new_ids - old_ids:
            _assign_run_to_group(run, group)
        elif run.trainee_id in old_ids - new_ids and run.group_id == group.id:
            _assign_run_to_group(run, sources.get(run.trainee.group_id))
        elif run.group_id == group.id:
            run.dds_profile = group.dds_profile or "ДДС"
            run.difficulty = group.difficulty
            run.queue_mode = group.queue_mode
    _invalidate_readiness(item)
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
    if payload.source_user_group_id != group.source_user_group_id:
        raise HTTPException(status_code=409, detail="Источник группы нельзя изменить")
    if group.source_user_group_id is not None:
        payload = payload.model_copy(update={"name": group.name})
    if any(other.name == payload.name and other.id != group_id for other in item.groups):
        raise HTTPException(status_code=409, detail="Группа с таким названием уже существует")
    for key, value in payload.model_dump().items():
        setattr(group, key, value)
    for run in item.runs:
        if run.group_id == group_id:
            run.dds_profile = group.dds_profile or "ДДС"
            run.difficulty = group.difficulty
            run.queue_mode = group.queue_mode
    _invalidate_readiness(item)
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
    if group.source_user_group_id is not None:
        source_user_ids = {user.id for user in group.source_group.members}
        if any(
            member.user_id in source_user_ids
            for subgroup in item.groups
            if subgroup.is_subgroup
            for member in subgroup.subgroup_memberships
        ):
            raise HTTPException(
                409, "Нельзя убрать группу: её участники входят в подгруппы занятия"
            )
    prepared_cards = list(
        (
            await database.scalars(
                select(ScenarioInstance)
                .where(ScenarioInstance.training_group_id == group_id)
                .options(selectinload(ScenarioInstance.events))
            )
        ).all()
    )
    if prepared_cards and not group.is_subgroup:
        raise HTTPException(409, "Сначала исключите подготовленные карточки группы")
    if group.is_subgroup:
        card_ids = {card.id for card in prepared_cards}
        queue_items = list(
            (
                await database.scalars(
                    select(ScenarioQueueItem).where(
                        or_(
                            ScenarioQueueItem.training_group_id == group_id,
                            ScenarioQueueItem.scenario_instance_id.in_(card_ids),
                        )
                    )
                )
            ).all()
        )
        for queue_item in queue_items:
            if queue_item in item.queue_items:
                item.queue_items.remove(queue_item)
            await database.delete(queue_item)
        await database.flush()
        for card in prepared_cards:
            if card in item.master_instances:
                item.master_instances.remove(card)
            await database.delete(card)
        await database.flush()
    for run in item.runs:
        if run.group_id == group_id:
            source = next(
                (
                    candidate
                    for candidate in item.groups
                    if candidate.source_user_group_id == run.trainee.group_id
                ),
                None,
            )
            _assign_run_to_group(run, source if group.is_subgroup else None)
    item.groups.remove(group)
    _invalidate_readiness(item)
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
    overrides = {"dds_profile", "difficulty", "queue_mode"} & payload.model_fields_set
    if payload.group_id is not None and overrides:
        raise HTTPException(
            status_code=422, detail="При назначении группы её параметры задаются самой группой"
        )
    if payload.group_id is None and payload.queue_mode == QueueMode.SHARED_QUEUE:
        raise HTTPException(status_code=422, detail="Общая очередь требует назначения группы")
    if not any(
        key in payload.model_fields_set
        for key in ("dds_profile", "difficulty", "queue_mode", "group_id")
    ):
        raise HTTPException(status_code=422, detail="Укажите назначаемые параметры")
    if (
        overrides
        and "group_id" not in payload.model_fields_set
        and any(run.group_id is not None for run in targets)
    ):
        raise HTTPException(status_code=422, detail="Сначала исключите участника из группы")
    if any(group.source_user_group_id is not None for group in item.groups):
        if overrides:
            raise HTTPException(422, "Параметры группы задаются на шаге «Группы»")
        for run in targets:
            run.group_id = payload.group_id
        _invalidate_readiness(item)
        return await _save(database, item)
    for run in targets:
        if payload.group_id is not None:
            group = next(group for group in item.groups if group.id == payload.group_id)
            run.dds_profile = group.dds_profile or "ДДС"
            run.difficulty = group.difficulty
            run.queue_mode = group.queue_mode
        for key in ("dds_profile", "difficulty", "queue_mode", "group_id"):
            if key in payload.model_fields_set and (payload.group_id is None or key == "group_id"):
                setattr(run, key, getattr(payload, key))
        if run.group_id is None and run.queue_mode == QueueMode.SHARED_QUEUE:
            run.queue_mode = QueueMode.INDIVIDUAL_QUEUE
    _invalidate_readiness(item)
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
    if any(group.source_user_group_id is not None for group in item.groups):
        groups = {group.id: group for group in item.groups}
        for run in item.runs:
            group = groups.get(run.group_id)
            run.dds_profile = (group.dds_profile or "ДДС") if group else "ДДС"
            run.difficulty = group.difficulty if group else None
            run.queue_mode = group.queue_mode if group else QueueMode.INDIVIDUAL_QUEUE
    try:
        start_training_session(item)
    except InvalidTrainingSessionTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    from app.modules.training.delivery import finalize_order
    from app.modules.training.prepared_pools import materialize_group_pools

    await materialize_group_pools(database, item)
    finalize_order(item)
    item.delivery_elapsed_seconds = 0
    item.delivery_checked_at = item.started_at
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
