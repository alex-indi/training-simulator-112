"""Проверки канонического snapshot и прав преподавателя."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import DDSResponseStatus, Incident, IncidentLifecycleState
from app.modules.training.models import TrainingRun, TrainingSession
from app.modules.training.monitor import _run_snapshot, _session
from app.modules.training.router import WorkstationView, set_workstation_view


def test_monitor_counts_shared_queue_once_and_keeps_offline_run() -> None:
    now = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    trainee = User(id=3, username="trainee", full_name="Иванов Иван", role=UserRole.TRAINEE)
    run = TrainingRun(
        id=7, trainee=trainee, trainee_id=3, workstation_number=7,
        open_incident_id=4,
        dds_profile="ДДС района", group_id=2, last_seen_at=now - timedelta(minutes=2),
    )
    shared = Incident(
        id=4, training_session_id=1, training_group_id=2, incident_number="КП-4",
        incident_type="Авария", address="Адрес", description="Описание", source="112",
        lifecycle_state=IncidentLifecycleState.DELIVERED,
        dds_status=DDSResponseStatus.AWAITING_DECISION,
        delivered_at=now - timedelta(seconds=50), actions=[], response_assignments=[],
    )
    own = Incident(
        id=5, training_session_id=1, training_run_id=7, incident_number="КП-5",
        incident_type="Авария", address="Адрес", description="Описание", source="112",
        lifecycle_state=IncidentLifecycleState.FINISHED,
        dds_status=DDSResponseStatus.COMPLETED,
        delivered_at=now - timedelta(minutes=5), actions=[], response_assignments=[],
    )

    snapshot = _run_snapshot(run, [shared, own], now)

    assert snapshot["online"] is False
    assert snapshot["counts"]["new"] == 1
    assert snapshot["counts"]["completed"] == 1
    assert snapshot["open_incident_id"] == 4
    assert {signal["kind"] for signal in snapshot["signals"]} == {"primary_status", "offline"}
    assert [incident["id"] for incident in snapshot["active_incidents"]] == [4]


def test_monitor_is_instructor_only_and_hides_other_sessions() -> None:
    session = TrainingSession(id=1, title="Смена", instructor_id=2)
    database = MagicMock()
    database.scalar = lambda *_: async_value(session)
    trainee = User(id=3, username="trainee", full_name="Обучаемый", role=UserRole.TRAINEE)
    other = User(id=4, username="other", full_name="Другой преподаватель", role=UserRole.INSTRUCTOR)

    for user in (trainee, other):
        with pytest.raises(HTTPException) as error:
            asyncio.run(_session(database, 1, user))
        assert error.value.status_code == 404


async def async_value(value):
    return value


def test_trainee_view_tracks_visible_card_and_rejects_foreign_card(monkeypatch) -> None:
    trainee = User(id=3, username="trainee", full_name="Обучаемый", role=UserRole.TRAINEE)
    run = TrainingRun(id=7, training_session_id=1, trainee_id=3, open_incident_id=None)
    own = Incident(id=4, training_session_id=1, training_run_id=7)
    foreign = Incident(id=5, training_session_id=1, training_run_id=8)
    database = MagicMock()
    database.scalar = AsyncMock(side_effect=[run, own, run, foreign])
    database.commit = AsyncMock()
    published = AsyncMock()
    monkeypatch.setattr("app.modules.training.router.publish_session_event", published)

    asyncio.run(set_workstation_view(1, WorkstationView(incident_id=4), trainee, database))
    assert run.open_incident_id == 4
    database.commit.assert_awaited_once()
    published.assert_awaited_once_with("training.workstation_view_changed", 1, 4)

    with pytest.raises(HTTPException) as error:
        asyncio.run(set_workstation_view(1, WorkstationView(incident_id=5), trainee, database))
    assert error.value.status_code == 404
    assert run.open_incident_id == 4

    database.scalar = AsyncMock(return_value=run)
    asyncio.run(set_workstation_view(1, WorkstationView(incident_id=None), trainee, database))
    assert run.open_incident_id is None
    assert published.await_count == 2
