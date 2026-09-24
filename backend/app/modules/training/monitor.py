"""Канонический read-only snapshot live-монитора преподавателя."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import DDSResponseStatus, Incident, IncidentLifecycleState
from app.modules.response.models import ResponseAssignment
from app.modules.training.clock import active_seconds
from app.modules.training.models import TrainingRun, TrainingSession

router = APIRouter(prefix="/api/training/sessions", tags=["training monitor"])
ONLINE_WINDOW = timedelta(seconds=45)
PRIMARY_STATUS_LIMIT = timedelta(seconds=30)


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


async def _session(database: AsyncSession, session_id: int, user: User) -> TrainingSession:
    item = await database.scalar(
        select(TrainingSession)
        .where(TrainingSession.id == session_id)
        .options(selectinload(TrainingSession.runs).selectinload(TrainingRun.trainee))
        .options(
            selectinload(TrainingSession.pauses),
            selectinload(TrainingSession.runs).selectinload(TrainingRun.pauses),
        )
    )
    if item is None or (
        user.role != UserRole.ADMIN
        and (user.role != UserRole.INSTRUCTOR or item.instructor_id != user.id)
    ):
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    return item


async def _incidents(database: AsyncSession, session_id: int) -> list[Incident]:
    result = await database.scalars(
        select(Incident)
        .where(Incident.training_session_id == session_id)
        .options(
            selectinload(Incident.actions),
            selectinload(Incident.scenario_events),
            selectinload(Incident.response_assignments).selectinload(
                ResponseAssignment.response_unit
            ),
            selectinload(Incident.response_assignments).selectinload(ResponseAssignment.events),
            selectinload(Incident.response_assignments).selectinload(ResponseAssignment.messages),
        )
        .order_by(Incident.delivered_at.desc(), Incident.id.desc())
    )
    return list(result.all())


def _owner(incident: Incident) -> int | None:
    return incident.claimed_by_training_run_id or incident.training_run_id


def _is_new(incident: Incident) -> bool:
    return (
        incident.lifecycle_state == IncidentLifecycleState.DELIVERED and incident.opened_at is None
    )


def _is_done(incident: Incident) -> bool:
    return incident.lifecycle_state == IncidentLifecycleState.FINISHED or incident.dds_status in {
        DDSResponseStatus.REJECTED,
        DDSResponseStatus.COMPLETED,
        DDSResponseStatus.WORK_REFUSED,
    }


def _incident_read(
    incident: Incident,
    now: datetime,
    session_pauses: list | None = None,
    run_pauses: list | None = None,
) -> dict:
    return {
        "id": incident.id,
        "scenario_instance_id": incident.scenario_instance_id,
        "incident_number": incident.incident_number,
        "incident_type": incident.incident_type,
        "address": incident.address,
        "description": incident.description,
        "source": incident.source,
        "applicant_name": incident.applicant_name,
        "training_group_id": incident.training_group_id,
        "training_run_id": incident.training_run_id,
        "claimed_by_training_run_id": incident.claimed_by_training_run_id,
        "lifecycle_state": incident.lifecycle_state,
        "dds_status": incident.dds_status,
        "delivered_at": incident.delivered_at,
        "opened_at": incident.opened_at,
        "finished_at": incident.finished_at,
        "elapsed_seconds": int(
            active_seconds(incident.delivered_at, now, session_pauses, run_pauses)
        )
        if incident.delivered_at
        else 0,
        "actions": [
            {
                "id": action.id,
                "status": action.status,
                "comment": action.comment,
                "actor_display_name": action.actor_display_name,
                "created_at": action.created_at,
            }
            for action in incident.actions
        ],
        "scenario_events": [
            {
                "id": event.id,
                "kind": event.kind,
                "body": event.body,
                "origin": event.origin,
                "created_at": event.created_at,
            }
            for event in (incident.scenario_events or [])
        ],
        "response_assignments": [
            {
                "id": assignment.id,
                "unit_name": assignment.response_unit.name,
                "state": assignment.state,
                "events": [
                    {"state": event.to_state, "created_at": event.created_at}
                    for event in assignment.events
                ],
                "messages": [
                    {
                        "id": message.id,
                        "sender_type": message.sender_type,
                        "body": message.body,
                        "created_at": message.created_at,
                        "read_at": message.read_at,
                    }
                    for message in assignment.messages
                ],
            }
            for assignment in incident.response_assignments
        ],
    }


def _run_snapshot(
    run: TrainingRun, incidents: list[Incident], now: datetime, session_pauses: list | None = None
) -> dict:
    owned = [incident for incident in incidents if _owner(incident) == run.id]
    available = [
        incident
        for incident in incidents
        if (
            incident.training_group_id is not None
            and incident.training_group_id == run.group_id
            and _owner(incident) is None
        )
    ]
    visible = owned + available
    active = [incident for incident in owned if not _is_done(incident)]
    current = next((incident for incident in active if incident.opened_at), None)
    if current is None:
        current = active[0] if active else None
    online = bool(run.last_seen_at and now - _aware(run.last_seen_at) < ONLINE_WINDOW)
    signals = []
    for incident in visible:
        if (
            _is_new(incident)
            and incident.primary_status_at is None
            and incident.delivered_at
            and active_seconds(incident.delivered_at, now, session_pauses, run.pauses)
            >= PRIMARY_STATUS_LIMIT.total_seconds()
        ):
            signals.append(
                {
                    "kind": "primary_status",
                    "severity": "high",
                    "incident_id": incident.id,
                    "text": f"{incident.incident_number}: нет первичного статуса",
                }
            )
    new_count = sum(_is_new(incident) for incident in visible)
    if new_count >= 4:
        signals.append(
            {
                "kind": "backlog",
                "severity": "medium",
                "incident_id": None,
                "text": f"{new_count} необработанные карточки",
            }
        )
    refusals = sum(
        incident.dds_status
        in {
            DDSResponseStatus.REJECTED,
            DDSResponseStatus.WORK_REFUSED,
        }
        for incident in owned
    )
    if refusals >= 2:
        signals.append(
            {
                "kind": "refusals",
                "severity": "medium",
                "incident_id": None,
                "text": f"Повторные отказы: {refusals}",
            }
        )
    if not online:
        signals.append(
            {"kind": "offline", "severity": "low", "incident_id": None, "text": "АРМ offline"}
        )

    timeline = []
    for incident in owned:
        if incident.delivered_at:
            timeline.append(
                {
                    "at": incident.delivered_at,
                    "incident_id": incident.id,
                    "text": f"{incident.incident_number}: карточка поступила",
                }
            )
        if incident.opened_at:
            timeline.append(
                {
                    "at": incident.opened_at,
                    "incident_id": incident.id,
                    "text": f"{incident.incident_number}: карточка открыта",
                }
            )
        for action in incident.actions:
            timeline.append(
                {
                    "at": action.created_at,
                    "incident_id": incident.id,
                    "text": f"{incident.incident_number}: {action.status}",
                }
            )
        for assignment in incident.response_assignments:
            for event in assignment.events:
                timeline.append(
                    {
                        "at": event.created_at,
                        "incident_id": incident.id,
                        "text": (
                            f"{incident.incident_number}: группа «{assignment.response_unit.name}» "
                            f"→ {event.to_state.value}"
                        ),
                    }
                )
            for message in assignment.messages:
                timeline.append(
                    {
                        "at": message.created_at,
                        "incident_id": incident.id,
                        "text": (
                            f"{incident.incident_number}: сообщение группы "
                            f"«{assignment.response_unit.name}»"
                        ),
                    }
                )
                if message.read_at:
                    timeline.append(
                        {
                            "at": message.read_at,
                            "incident_id": incident.id,
                            "text": f"{incident.incident_number}: сообщение группы прочитано",
                        }
                    )
    timeline.sort(key=lambda entry: (_aware(entry["at"]), entry["incident_id"]), reverse=True)

    return {
        "id": run.id,
        "workstation_number": run.workstation_number,
        "trainee_name": run.trainee.full_name,
        "dds_profile": run.dds_profile,
        "group_id": run.group_id,
        "online": online,
        "last_seen_at": run.last_seen_at,
        "paused_at": run.paused_at,
        "counts": {
            "new": new_count,
            "working": sum(not _is_done(incident) and not _is_new(incident) for incident in owned),
            "completed": sum(_is_done(incident) for incident in owned),
            "refusals": refusals,
            "deviations": len([signal for signal in signals if signal["kind"] != "offline"]),
        },
        "current": _incident_read(current, now, session_pauses, run.pauses) if current else None,
        "active_incidents": [
            _incident_read(incident, now, session_pauses, run.pauses)
            for incident in visible
            if not _is_done(incident)
        ],
        "signals": signals,
        "timeline": timeline[:30],
    }


@router.get("/{training_session_id}/monitor")
async def get_monitor(
    training_session_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    """Полный snapshot восстанавливается после reload или Socket.IO reconnect."""
    session = await _session(database, training_session_id, current_user)
    incidents = await _incidents(database, session.id)
    now = datetime.now(UTC)
    runs = [
        _run_snapshot(run, incidents, now, session.pauses)
        for run in sorted(session.runs, key=lambda run: (run.workstation_number or 9999, run.id))
    ]
    attention = [
        dict(signal, run_id=run["id"], workstation_number=run["workstation_number"])
        for run in runs
        for signal in run["signals"]
    ]
    severity_order = {"high": 0, "medium": 1, "low": 2}
    attention.sort(
        key=lambda signal: (
            severity_order[signal["severity"]],
            signal["workstation_number"] or 9999,
        )
    )
    return {
        "session": {
            "id": session.id,
            "title": session.title,
            "topic": session.topic,
            "state": session.state,
            "started_at": session.started_at,
            "paused_at": session.paused_at,
            "paused_seconds": session.paused_seconds or 0,
            "finish_mode": session.finish_mode,
            "completed_at": session.completed_at,
            "delivery_elapsed_seconds": session.delivery_elapsed_seconds or 0,
            "delivery_checked_at": session.delivery_checked_at,
            "duration_minutes": session.duration_minutes,
        },
        "server_time": now,
        "counts": {
            "online": sum(run["online"] for run in runs),
            "offline": sum(not run["online"] for run in runs),
            "new": sum(_is_new(incident) for incident in incidents),
            "working": sum(
                not _is_new(incident) and not _is_done(incident) for incident in incidents
            ),
            "completed": sum(_is_done(incident) for incident in incidents),
            "deviations": sum(run["counts"]["deviations"] for run in runs),
        },
        "runs": runs,
        "attention": attention,
    }


@router.get("/{training_session_id}/runs/{run_id}/workstation")
async def get_workstation(
    training_session_id: int,
    run_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    """Серверное состояние АРМ без команд изменения от имени обучаемого."""
    session = await _session(database, training_session_id, current_user)
    run = next((item for item in session.runs if item.id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    incidents = await _incidents(database, session.id)
    now = datetime.now(UTC)
    snapshot = _run_snapshot(run, incidents, now, session.pauses)
    owned = [incident for incident in incidents if _owner(incident) == run.id]
    shared = [
        incident
        for incident in incidents
        if (incident.training_group_id is not None and incident.training_group_id == run.group_id)
    ]
    visible = {incident.id: incident for incident in owned + shared}
    snapshot["incidents"] = [
        _incident_read(incident, now, session.pauses, run.pauses) for incident in visible.values()
    ]
    return snapshot
