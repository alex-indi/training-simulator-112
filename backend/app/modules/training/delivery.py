"""Подготовка и атомарная выдача карточек по серверному времени."""

import asyncio
import logging
import math
import random
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.incidents.schemas import IncidentSnapshot
from app.modules.incidents.workflow import create_delivered_incident
from app.modules.training.models import (
    DeliveryOrder,
    DeliveryState,
    QueueMode,
    ScenarioQueueItem,
    TrainingMode,
    TrainingScenario,
    TrainingSession,
    TrainingSessionState,
)
from app.modules.training.router import _ensure_session_owner, _load_session
from app.modules.training.schemas import (
    GenerateQueueRequest,
    QueueItemRead,
    QueueItemUpdate,
    QueueItemWrite,
)

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/training/sessions", tags=["scenario queue"])


def _read_queue(session: TrainingSession) -> list[QueueItemRead]:
    return [
        QueueItemRead.model_validate(item, from_attributes=True)
        for item in sorted(session.queue_items, key=lambda item: item.position)
    ]


def _editable(session: TrainingSession, user: User) -> None:
    _ensure_session_owner(session, user)
    if session.state not in (TrainingSessionState.DRAFT, TrainingSessionState.READY):
        raise HTTPException(409, "После запуска подготовленные карточки неизменяемы")


def _invalidate_readiness(session: TrainingSession) -> None:
    if session.state == TrainingSessionState.READY:
        session.state = TrainingSessionState.DRAFT


def _new_item(
    session: TrainingSession,
    run_id: int | None,
    title: str,
    snapshot: dict,
    group_id: int | None = None,
) -> ScenarioQueueItem:
    scenario = TrainingScenario(instructor_id=session.instructor_id, title=title, snapshot=snapshot)
    position = max((item.position for item in session.queue_items), default=0) + 1
    item = ScenarioQueueItem(
        training_run_id=run_id,
        training_group_id=group_id,
        scenario=scenario,
        title=title,
        snapshot=snapshot,
        position=position,
        approved=False,
    )
    session.queue_items.append(item)
    return item


@router.get("/{training_session_id}/queue", response_model=list[QueueItemRead])
async def read_queue(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[QueueItemRead]:
    session = await _load_session(database, training_session_id)
    _ensure_session_owner(session, current_user)
    return _read_queue(session)


@router.post("/{training_session_id}/queue", response_model=list[QueueItemRead], status_code=201)
async def add_queue_item(
    training_session_id: int,
    payload: QueueItemWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[QueueItemRead]:
    session = await _load_session(database, training_session_id, for_update=True)
    _editable(session, current_user)
    if payload.training_run_id is not None and payload.training_run_id not in {
        run.id for run in session.runs if run.queue_mode == QueueMode.INDIVIDUAL_QUEUE
    }:
        raise HTTPException(422, "АРМ не принадлежит индивидуальной очереди занятия")
    if payload.training_group_id is not None and payload.training_group_id not in {
        group.id
        for group in session.groups
        if group.queue_mode == QueueMode.SHARED_QUEUE
        and any(run.group_id == group.id for run in session.runs)
    }:
        raise HTTPException(422, "Группа не принадлежит общей очереди занятия")
    _new_item(
        session,
        payload.training_run_id,
        payload.title.strip(),
        payload.snapshot.model_dump(mode="json"),
        group_id=payload.training_group_id,
    )
    _invalidate_readiness(session)
    await database.commit()
    return _read_queue(await _load_session(database, training_session_id))


@router.put("/{training_session_id}/queue/{queue_item_id}", response_model=list[QueueItemRead])
async def update_queue_item(
    training_session_id: int,
    queue_item_id: int,
    payload: QueueItemUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[QueueItemRead]:
    session = await _load_session(database, training_session_id, for_update=True)
    _editable(session, current_user)
    item = next((entry for entry in session.queue_items if entry.id == queue_item_id), None)
    if item is None:
        raise HTTPException(404, "Позиция не найдена")
    snapshot = payload.snapshot.model_dump(mode="json")
    item.title = payload.title.strip()
    item.snapshot = snapshot
    item.scenario = TrainingScenario(
        instructor_id=current_user.id, title=item.title, snapshot=snapshot
    )
    item.approved = False
    _invalidate_readiness(session)
    await database.commit()
    return _read_queue(await _load_session(database, training_session_id))


@router.delete("/{training_session_id}/queue/{queue_item_id}", response_model=list[QueueItemRead])
async def delete_queue_item(
    training_session_id: int,
    queue_item_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[QueueItemRead]:
    session = await _load_session(database, training_session_id, for_update=True)
    _editable(session, current_user)
    item = next((entry for entry in session.queue_items if entry.id == queue_item_id), None)
    if item is None:
        raise HTTPException(404, "Позиция не найдена")
    session.queue_items.remove(item)
    await database.flush()
    for position, entry in enumerate(
        sorted(session.queue_items, key=lambda value: value.position), 1
    ):
        entry.position = position
    _invalidate_readiness(session)
    await database.commit()
    return _read_queue(await _load_session(database, training_session_id))


@router.post("/{training_session_id}/queue/approve", response_model=list[QueueItemRead])
async def approve_queue(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[QueueItemRead]:
    session = await _load_session(database, training_session_id, for_update=True)
    _editable(session, current_user)
    if session.mode != TrainingMode.MANUAL and not session.queue_items:
        raise HTTPException(409, "Подготовьте карточки перед утверждением")
    for item in session.queue_items:
        item.approved = True
    await database.commit()
    return _read_queue(await _load_session(database, training_session_id))


SCENARIOS = [
    (
        "Прорыв трубопровода",
        "Вода поступает в подвальное помещение жилого дома",
        "Авария водоснабжения",
    ),
    ("Открытый люк", "У дома обнаружен открытый канализационный люк", "Опасность на улице"),
    ("Авария лифта", "Лифт остановился между этажами, внутри находятся люди", "Авария лифта"),
    (
        "Повреждение электросети",
        "На улице оборван провод линии электропередачи",
        "Повреждение электросети",
    ),
]


@router.post(
    "/{training_session_id}/queue/{queue_item_id}/replace", response_model=list[QueueItemRead]
)
async def replace_queue_item(
    training_session_id: int,
    queue_item_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[QueueItemRead]:
    session = await _load_session(database, training_session_id, for_update=True)
    _editable(session, current_user)
    item = next((entry for entry in session.queue_items if entry.id == queue_item_id), None)
    if item is None:
        raise HTTPException(404, "Позиция не найдена")
    current_index = next(
        (index for index, candidate in enumerate(SCENARIOS) if candidate[0] == item.title),
        -1,
    )
    title, description, incident_type = SCENARIOS[(current_index + 1) % len(SCENARIOS)]
    snapshot = {**item.snapshot, "description": description, "incident_type": incident_type}
    item.title = title
    item.snapshot = snapshot
    item.scenario = TrainingScenario(instructor_id=current_user.id, title=title, snapshot=snapshot)
    item.approved = False
    _invalidate_readiness(session)
    await database.commit()
    return _read_queue(await _load_session(database, training_session_id))


@router.post("/{training_session_id}/queue/generate", response_model=list[QueueItemRead])
async def generate_queue(
    training_session_id: int,
    payload: GenerateQueueRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[QueueItemRead]:
    session = await _load_session(database, training_session_id, for_update=True)
    _editable(session, current_user)
    if not session.runs:
        raise HTTPException(409, "Сначала подключите участников")
    session.queue_items.clear()
    await database.flush()
    targets = [
        (run.id, None, run.workstation_number)
        for run in session.runs
        if run.queue_mode != QueueMode.SHARED_QUEUE
    ]
    targets += [
        (None, group.id, group.name)
        for group in session.groups
        if group.queue_mode == QueueMode.SHARED_QUEUE
        and any(run.group_id == group.id for run in session.runs)
    ]
    for run_id, group_id, label in targets:
        for index in range(payload.count_per_run):
            title, description, incident_type = SCENARIOS[index % len(SCENARIOS)]
            sequence = index + 1
            snapshot = IncidentSnapshot(
                incident_number=f"КП-{session.id}-{run_id or 'G' + str(group_id)}-{sequence}",
                reported_at=datetime.now(UTC),
                source="Система-112",
                address=f"Учебный объект, участок {label}",
                description=description,
                incident_type=incident_type,
            ).model_dump(mode="json")
            _new_item(session, run_id, title, snapshot, group_id=group_id)
    _invalidate_readiness(session)
    await database.commit()
    return _read_queue(await _load_session(database, training_session_id))


def finalize_order(session: TrainingSession) -> None:
    """Порядок RANDOM фиксируется один раз при старте и не меняет содержимое."""
    targets = [("run", run.id) for run in session.runs if run.queue_mode != QueueMode.SHARED_QUEUE]
    targets += [
        ("group", group.id)
        for group in session.groups
        if group.queue_mode == QueueMode.SHARED_QUEUE
    ]
    for target_type, target_id in targets:
        ordered = sorted(
            (
                item
                for item in session.queue_items
                if (item.training_run_id if target_type == "run" else item.training_group_id)
                == target_id
            ),
            key=lambda item: item.position,
        )
        if session.delivery_order == DeliveryOrder.RANDOM:
            random.shuffle(ordered)
        for index, item in enumerate(ordered, 1):
            item.delivery_position = index


def due_items(session: TrainingSession, now: datetime) -> list[ScenarioQueueItem]:
    """Определяет карточки по накопленному учебному времени."""
    if session.state != TrainingSessionState.ACTIVE or session.mode == TrainingMode.MANUAL:
        return []
    pending = [item for item in session.queue_items if item.delivery_state == DeliveryState.PENDING]
    if session.mode == TrainingMode.FIXED_SET:
        return pending
    elapsed = session.delivery_elapsed_seconds or 0
    if session.delivery_checked_at:
        elapsed += max(0, (now - session.delivery_checked_at).total_seconds())
    if session.duration_minutes and elapsed > session.duration_minutes * 60:
        elapsed = session.duration_minutes * 60
    interval = session.delivery_interval_seconds or 120
    due_per_run = int(elapsed // interval + 1)
    if session.duration_minutes:
        due_per_run = min(
            due_per_run,
            math.ceil(session.duration_minutes * 60 / interval),
        )
    due = [item for item in pending if (item.delivery_position or item.position) <= due_per_run]
    return sorted(due, key=lambda item: (item.delivery_position or item.position, item.position))


async def tick_session(database: AsyncSession, session_id: int, now: datetime) -> list[int]:
    """Одна транзакция блокирует занятие и связывает очередь с Incident."""
    statement = (
        select(TrainingSession)
        .where(TrainingSession.id == session_id)
        .with_for_update(skip_locked=True, of=TrainingSession)
        .options(selectinload(TrainingSession.queue_items))
    )
    session = (await database.scalars(statement)).one_or_none()
    if session is None or session.state != TrainingSessionState.ACTIVE:
        return []
    pending = due_items(session, now)
    if session.delivery_checked_at is not None:
        session.delivery_elapsed_seconds += max(
            0, (now - session.delivery_checked_at).total_seconds()
        )
    session.delivery_checked_at = now
    incident_ids = []
    for item in pending:
        incident = create_delivered_incident(
            training_session_id=session.id, source_snapshot=item.snapshot, server_time=now
        )
        incident.training_run_id = item.training_run_id
        incident.training_group_id = item.training_group_id
        database.add(incident)
        await database.flush()
        item.delivery_state = DeliveryState.DELIVERED
        item.delivered_at = now
        item.incident_id = incident.id
        incident_ids.append(incident.id)
    await database.commit()
    return incident_ids


async def scheduler_loop(session_factory, notify) -> None:
    """Каждая итерация перечитывает БД; после перезапуска прогресс не теряется."""
    while True:
        try:
            async with session_factory() as database:
                session_ids = (
                    await database.scalars(
                        select(TrainingSession.id).where(
                            TrainingSession.state == TrainingSessionState.ACTIVE
                        )
                    )
                ).all()
            for session_id in session_ids:
                async with session_factory() as database:
                    delivered = await tick_session(database, session_id, datetime.now(UTC))
                for incident_id in delivered:
                    await notify(session_id, incident_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка выдачи карточек")
        await asyncio.sleep(1)
