"""Команды преподавателя для активной учебной смены."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.incidents.models import Incident
from app.modules.incidents.workflow import create_delivered_incident
from app.modules.scenario_library.runtime import prepare_runtime_events
from app.modules.training.models import (
    DeliveryState,
    InstructorAction,
    InstructorNote,
    RunPause,
    ScenarioEvent,
    SessionPause,
    TrainingSessionState,
)
from app.modules.training.router import _ensure_session_owner, _load_session
from app.realtime import publish_session_event

router = APIRouter(prefix="/api/training/sessions", tags=["instructor control"])


class PauseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Укажите причину")
        return value.strip()


class ManualCardRequest(BaseModel):
    scenario_id: int
    target: Literal["RUN", "GROUP", "CLASS"]
    target_id: int | None = None


class ScenarioEventRequest(BaseModel):
    incident_id: int
    kind: Literal[
        "OBJECT_CLARIFIED",
        "REPEAT_CALL",
        "SITUATION_CHANGED",
        "CASUALTY",
        "NEW_INFORMATION",
        "UNIT_UNAVAILABLE",
        "PARTICIPANT_MESSAGE",
    ]
    body: str = Field(min_length=1, max_length=3000)

    @field_validator("body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Укажите текст события")
        return value.strip()


class NoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Укажите текст заметки")
        return value.strip()


class FinishRequest(BaseModel):
    mode: Literal["GRACEFUL", "IMMEDIATE"] = "GRACEFUL"


def _audit(session_id: int, user_id: int, action: str, details: dict) -> InstructorAction:
    return InstructorAction(
        training_session_id=session_id, instructor_id=user_id, action=action, details=details
    )


async def _active(database: AsyncSession, session_id: int, user: User):
    session = await _load_session(database, session_id, for_update=True)
    _ensure_session_owner(session, user)
    if session.state != TrainingSessionState.ACTIVE:
        raise HTTPException(409, "Занятие не активно")
    return session


async def _notify(session_id: int, event: str, item_id: int | None = None) -> None:
    await publish_session_event(event, session_id, item_id)


@router.post("/{session_id}/pause")
async def pause_session(
    session_id: int,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _active(database, session_id, user)
    if session.paused_at:
        raise HTTPException(409, "Занятие уже приостановлено")
    now = datetime.now(UTC)
    if session.delivery_checked_at:
        session.delivery_elapsed_seconds += max(
            0, (now - session.delivery_checked_at).total_seconds()
        )
    session.delivery_checked_at = None
    session.paused_at = now
    database.add_all(
        [
            SessionPause(training_session_id=session.id, instructor_id=user.id, started_at=now),
            _audit(session.id, user.id, "pause", {}),
        ]
    )
    await database.commit()
    await _notify(session.id, "training.control_changed")
    return {"paused_at": now}


@router.post("/{session_id}/resume")
async def resume_session(
    session_id: int,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _active(database, session_id, user)
    if not session.paused_at:
        raise HTTPException(409, "Занятие не приостановлено")
    now = datetime.now(UTC)
    session.paused_seconds += max(0, (now - session.paused_at).total_seconds())
    session.paused_at = None
    session.delivery_checked_at = now
    pause = await database.scalar(
        select(SessionPause)
        .where(SessionPause.training_session_id == session.id, SessionPause.finished_at.is_(None))
        .order_by(SessionPause.id.desc())
        .limit(1)
    )
    if pause:
        pause.finished_at = now
        pause.duration_seconds = max(0, (now - pause.started_at).total_seconds())
    database.add(_audit(session.id, user.id, "resume", {}))
    await database.commit()
    await _notify(session.id, "training.control_changed")
    return {"paused_seconds": session.paused_seconds}


@router.post("/{session_id}/runs/{run_id}/pause")
async def pause_run(
    session_id: int,
    run_id: int,
    payload: PauseRequest,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _active(database, session_id, user)
    run = next((item for item in session.runs if item.id == run_id), None)
    if run is None:
        raise HTTPException(404, "АРМ не найден")
    if run.paused_at:
        raise HTTPException(409, "АРМ уже приостановлен")
    now = datetime.now(UTC)
    run.paused_at = now
    pause = RunPause(
        training_run_id=run.id, instructor_id=user.id, reason=payload.reason.strip(), started_at=now
    )
    database.add_all(
        [
            pause,
            _audit(
                session.id, user.id, "individual_pause", {"run_id": run.id, "reason": pause.reason}
            ),
        ]
    )
    await database.commit()
    await _notify(session.id, "training.control_changed")
    return {"paused_at": now, "reason": pause.reason}


@router.post("/{session_id}/runs/{run_id}/resume")
async def resume_run(
    session_id: int,
    run_id: int,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _active(database, session_id, user)
    run = next((item for item in session.runs if item.id == run_id), None)
    if run is None:
        raise HTTPException(404, "АРМ не найден")
    if not run.paused_at:
        raise HTTPException(409, "АРМ не приостановлен")
    now = datetime.now(UTC)
    duration = max(0, (now - run.paused_at).total_seconds())
    run.paused_seconds += duration
    run.paused_at = None
    pause = await database.scalar(
        select(RunPause)
        .where(RunPause.training_run_id == run_id, RunPause.finished_at.is_(None))
        .order_by(RunPause.id.desc())
        .limit(1)
    )
    if pause:
        pause.finished_at = now
        pause.duration_seconds = duration
    database.add(
        _audit(
            session.id,
            user.id,
            "individual_resume",
            {"run_id": run.id, "duration_seconds": duration},
        )
    )
    await database.commit()
    await _notify(session.id, "training.control_changed")
    return {"duration_seconds": duration}


@router.get("/{session_id}/scenarios")
async def list_scenarios(
    session_id: int,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    session = await _load_session(database, session_id)
    _ensure_session_owner(session, user)
    return [
        {
            "id": item.scenario_id,
            "title": item.title,
            "scenario_instance_id": item.scenario_instance_id,
            "training_run_id": item.training_run_id,
            "training_group_id": item.training_group_id,
        }
        for item in session.queue_items
        if item.approved and item.scenario_id is not None
    ]


@router.post("/{session_id}/manual-cards", status_code=201)
async def send_manual_card(
    session_id: int,
    payload: ManualCardRequest,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _active(database, session_id, user)
    if session.paused_at or session.finish_mode:
        raise HTTPException(409, "Во время паузы или завершения новые карточки не выдаются")
    prepared = next(
        (
            item
            for item in session.queue_items
            if item.scenario_id == payload.scenario_id and item.approved
        ),
        None,
    )
    if prepared is None:
        raise HTTPException(404, "Подготовленный сценарий не найден")
    if prepared.scenario_instance_id is not None and prepared.incident_id is not None:
        return {"incident_ids": [prepared.incident_id]}
    if prepared.scenario_instance_id is not None and prepared.training_group_id is not None:
        if payload.target != "GROUP" or payload.target_id != prepared.training_group_id:
            raise HTTPException(422, "Экземпляр подготовлен для указанной общей группы")
        if not any(
            run.group_id == prepared.training_group_id and not run.paused_at for run in session.runs
        ):
            raise HTTPException(409, "Все АРМ группы приостановлены")
        now = datetime.now(UTC)
        incident = create_delivered_incident(
            training_session_id=session.id, source_snapshot=prepared.snapshot, server_time=now
        )
        incident.training_group_id = prepared.training_group_id
        incident.scenario_instance_id = prepared.scenario_instance_id
        database.add(incident)
        await database.flush()
        await prepare_runtime_events(database, incident)
        prepared.incident_id = incident.id
        prepared.delivery_state = DeliveryState.DELIVERED
        prepared.delivered_at = now
        database.add(
            _audit(session.id, user.id, "manual_incident", {"incident_ids": [incident.id]})
        )
        await database.commit()
        await _notify(session.id, "incident.delivered", incident.id)
        return {"incident_ids": [incident.id]}
    if payload.target == "RUN":
        targets = [run for run in session.runs if run.id == payload.target_id]
    elif payload.target == "GROUP":
        targets = [run for run in session.runs if run.group_id == payload.target_id]
    else:
        targets = list(session.runs)
    if not targets:
        raise HTTPException(422, "Получатели не найдены")
    targets = [run for run in targets if not run.paused_at]
    if prepared.scenario_instance_id is not None:
        if len(targets) != 1 or targets[0].id != prepared.training_run_id:
            raise HTTPException(422, "Экземпляр подготовлен для одного указанного АРМ")
    if not targets:
        raise HTTPException(409, "Все выбранные АРМ приостановлены")
    now = datetime.now(UTC)
    ids = []
    for run in targets:
        snapshot = dict(prepared.snapshot)
        suffix = f"-M{run.id}-{uuid4().hex[:8]}"
        snapshot["incident_number"] = snapshot["incident_number"][: 64 - len(suffix)] + suffix
        incident = create_delivered_incident(
            training_session_id=session.id, source_snapshot=snapshot, server_time=now
        )
        incident.training_run_id = run.id
        incident.scenario_instance_id = prepared.scenario_instance_id
        database.add(incident)
        await database.flush()
        await prepare_runtime_events(database, incident)
        if prepared.scenario_instance_id is not None:
            prepared.incident_id = incident.id
            prepared.delivery_state = DeliveryState.DELIVERED
            prepared.delivered_at = now
        ids.append(incident.id)
    database.add(
        _audit(
            session.id,
            user.id,
            "manual_incident",
            {
                "scenario_id": prepared.scenario_id,
                "target": payload.target,
                "target_id": payload.target_id,
                "incident_ids": ids,
            },
        )
    )
    await database.commit()
    for incident_id in ids:
        await _notify(session.id, "incident.delivered", incident_id)
    return {"incident_ids": ids}


@router.post("/{session_id}/scenario-events", status_code=201)
async def add_scenario_event(
    session_id: int,
    payload: ScenarioEventRequest,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _active(database, session_id, user)
    if session.paused_at:
        raise HTTPException(409, "События приостановлены")
    incident = await database.scalar(
        select(Incident).where(
            Incident.id == payload.incident_id, Incident.training_session_id == session.id
        )
    )
    if incident is None:
        raise HTTPException(404, "Карточка не найдена")
    event = ScenarioEvent(
        incident_id=incident.id, instructor_id=user.id, kind=payload.kind, body=payload.body.strip()
    )
    database.add_all(
        [
            event,
            _audit(
                session.id,
                user.id,
                "scenario_event",
                {"incident_id": incident.id, "kind": payload.kind},
            ),
        ]
    )
    await database.commit()
    await _notify(session.id, "incident.updated", incident.id)
    return {"id": event.id, "created_at": event.created_at}


@router.post("/{session_id}/runs/{run_id}/notes", status_code=201)
async def add_note(
    session_id: int,
    run_id: int,
    payload: NoteRequest,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _active(database, session_id, user)
    if run_id not in {run.id for run in session.runs}:
        raise HTTPException(404, "АРМ не найден")
    note = InstructorNote(training_run_id=run_id, instructor_id=user.id, body=payload.body.strip())
    database.add_all([note, _audit(session.id, user.id, "instructor_note", {"run_id": run_id})])
    await database.commit()
    return {"id": note.id, "body": note.body, "created_at": note.created_at}


@router.get("/{session_id}/runs/{run_id}/notes")
async def list_notes(
    session_id: int,
    run_id: int,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    session = await _load_session(database, session_id)
    _ensure_session_owner(session, user)
    if run_id not in {run.id for run in session.runs}:
        raise HTTPException(404, "АРМ не найден")
    notes = (
        await database.scalars(
            select(InstructorNote)
            .where(InstructorNote.training_run_id == run_id)
            .order_by(InstructorNote.id)
        )
    ).all()
    return [
        {
            "id": note.id,
            "body": note.body,
            "created_at": note.created_at,
            "instructor_id": note.instructor_id,
        }
        for note in notes
    ]


@router.post("/{session_id}/finish")
async def finish_session(
    session_id: int,
    payload: FinishRequest,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _active(database, session_id, user)
    if session.finish_mode and not (
        session.finish_mode == "GRACEFUL" and payload.mode == "IMMEDIATE"
    ):
        raise HTTPException(409, "Завершение уже запрошено")
    now = datetime.now(UTC)
    if session.paused_at:
        duration = max(0, (now - session.paused_at).total_seconds())
        session.paused_seconds += duration
        session.paused_at = None
        pause = await database.scalar(
            select(SessionPause)
            .where(
                SessionPause.training_session_id == session.id, SessionPause.finished_at.is_(None)
            )
            .order_by(SessionPause.id.desc())
            .limit(1)
        )
        if pause:
            pause.finished_at = now
            pause.duration_seconds = duration
        database.add(_audit(session.id, user.id, "resume", {"for_finish": True}))
    if session.delivery_checked_at:
        session.delivery_elapsed_seconds += max(
            0, (now - session.delivery_checked_at).total_seconds()
        )
    session.delivery_checked_at = None
    session.finish_mode = payload.mode
    if payload.mode == "IMMEDIATE":
        for run in session.runs:
            if not run.paused_at:
                continue
            duration = max(0, (now - run.paused_at).total_seconds())
            run.paused_seconds += duration
            run.paused_at = None
            pause = await database.scalar(
                select(RunPause)
                .where(RunPause.training_run_id == run.id, RunPause.finished_at.is_(None))
                .order_by(RunPause.id.desc())
                .limit(1)
            )
            if pause:
                pause.finished_at = now
                pause.duration_seconds = duration
        session.state = TrainingSessionState.COMPLETED
        session.completed_at = now
    database.add(_audit(session.id, user.id, "finish_request", {"mode": payload.mode}))
    await database.commit()
    await _notify(session.id, "training.control_changed")
    return {"state": session.state, "finish_mode": session.finish_mode}


@router.get("/{session_id}/actions")
async def list_instructor_actions(
    session_id: int,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    session = await _load_session(database, session_id)
    _ensure_session_owner(session, user)
    actions = (
        await database.scalars(
            select(InstructorAction)
            .where(InstructorAction.training_session_id == session_id)
            .order_by(InstructorAction.id)
        )
    ).all()
    return [
        {
            "id": item.id,
            "action": item.action,
            "details": item.details,
            "instructor_id": item.instructor_id,
            "created_at": item.created_at,
        }
        for item in actions
    ]
