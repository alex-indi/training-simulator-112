"""Проверки канонического snapshot и прав преподавателя."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import DDSResponseStatus, Incident, IncidentLifecycleState
from app.modules.training.models import TrainingRun, TrainingSession
from app.modules.training.monitor import _run_snapshot, _session


def test_monitor_counts_shared_queue_once_and_keeps_offline_run() -> None:
    now = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    trainee = User(id=3, username="trainee", full_name="Иванов Иван", role=UserRole.TRAINEE)
    run = TrainingRun(
        id=7, trainee=trainee, trainee_id=3, workstation_number=7,
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
