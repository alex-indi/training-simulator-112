"""Регрессии управления активной сменой и учебного времени."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.response import models as response_models  # noqa: F401
from app.modules.training.clock import active_seconds
from app.modules.training.control import (
    FinishRequest,
    finish_session,
    pause_session,
    send_manual_card,
)
from app.modules.training.delivery import due_items
from app.modules.training.models import (
    DeliveryState,
    RunPause,
    ScenarioQueueItem,
    SessionPause,
    TrainingMode,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
)


def test_overlapping_global_and_individual_pauses_count_once():
    start = datetime(2026, 9, 24, 10, tzinfo=UTC)
    global_pause = SessionPause(
        started_at=start + timedelta(seconds=10), finished_at=start + timedelta(seconds=30)
    )
    run_pause = RunPause(
        started_at=start + timedelta(seconds=20), finished_at=start + timedelta(seconds=40)
    )
    assert active_seconds(start, start + timedelta(seconds=50), [global_pause], [run_pause]) == 20


def test_individual_pause_delays_only_its_queue():
    start = datetime(2026, 9, 24, 10, tzinfo=UTC)
    first = TrainingRun(
        id=1,
        paused_seconds=60,
        pauses=[
            RunPause(
                started_at=start + timedelta(seconds=10), finished_at=start + timedelta(seconds=70)
            )
        ],
    )
    second = TrainingRun(id=2, paused_seconds=0, pauses=[])
    session = TrainingSession(
        id=4,
        state=TrainingSessionState.ACTIVE,
        mode=TrainingMode.FLOW,
        started_at=start,
        delivery_interval_seconds=60,
        delivery_elapsed_seconds=0,
        delivery_checked_at=start,
        runs=[first, second],
        pauses=[],
        queue_items=[
            ScenarioQueueItem(
                id=1,
                training_run_id=1,
                position=1,
                delivery_position=2,
                delivery_state=DeliveryState.PENDING,
            ),
            ScenarioQueueItem(
                id=2,
                training_run_id=2,
                position=2,
                delivery_position=2,
                delivery_state=DeliveryState.PENDING,
            ),
        ],
    )
    assert [item.id for item in due_items(session, start + timedelta(seconds=70))] == [2]


def test_scheduler_has_no_due_cards_during_global_pause_or_finish():
    start = datetime(2026, 9, 24, 10, tzinfo=UTC)
    session = TrainingSession(
        state=TrainingSessionState.ACTIVE,
        mode=TrainingMode.FIXED_SET,
        queue_items=[ScenarioQueueItem(position=1, delivery_state=DeliveryState.PENDING)],
        paused_at=start,
    )
    assert due_items(session, start) == []
    session.paused_at = None
    session.finish_mode = "GRACEFUL"
    assert due_items(session, start) == []


def test_pause_records_audit_and_freezes_scheduler(monkeypatch):
    now = datetime.now(UTC)
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = TrainingSession(
        id=4,
        instructor_id=2,
        state=TrainingSessionState.ACTIVE,
        delivery_checked_at=now - timedelta(seconds=30),
        delivery_elapsed_seconds=10,
    )
    database = MagicMock()
    database.commit = AsyncMock()
    monkeypatch.setattr("app.modules.training.control._active", AsyncMock(return_value=session))
    monkeypatch.setattr("app.modules.training.control._notify", AsyncMock())
    result = asyncio.run(pause_session(4, instructor, database))
    assert result["paused_at"] == session.paused_at
    assert session.delivery_checked_at is None
    assert session.delivery_elapsed_seconds >= 40
    assert {item.__class__.__name__ for item in database.add_all.call_args.args[0]} == {
        "SessionPause",
        "InstructorAction",
    }


def test_manual_card_rejected_during_global_pause(monkeypatch):
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = TrainingSession(
        id=4,
        instructor_id=2,
        state=TrainingSessionState.ACTIVE,
        paused_at=datetime.now(UTC),
        queue_items=[],
    )
    monkeypatch.setattr("app.modules.training.control._active", AsyncMock(return_value=session))
    from app.modules.training.control import ManualCardRequest

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            send_manual_card(
                4, ManualCardRequest(scenario_id=1, target="CLASS"), instructor, MagicMock()
            )
        )
    assert error.value.status_code == 409


def test_immediate_finish_preserves_incidents_and_audits_request(monkeypatch):
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = TrainingSession(
        id=4,
        instructor_id=2,
        state=TrainingSessionState.ACTIVE,
        finish_mode="GRACEFUL",
        runs=[],
        delivery_elapsed_seconds=100,
    )
    database = MagicMock()
    database.commit = AsyncMock()
    monkeypatch.setattr("app.modules.training.control._active", AsyncMock(return_value=session))
    monkeypatch.setattr("app.modules.training.control._notify", AsyncMock())
    result = asyncio.run(finish_session(4, FinishRequest(mode="IMMEDIATE"), instructor, database))
    assert result == {"state": TrainingSessionState.COMPLETED, "finish_mode": "IMMEDIATE"}
    assert session.completed_at is not None
    audit = database.add.call_args.args[0]
    assert audit.action == "finish_request"
    assert audit.details == {"mode": "IMMEDIATE"}
