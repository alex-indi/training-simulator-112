"""Общая выдача и серверные права участников одной ДДС."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.incidents.router import _ensure_incident_visible, _to_read_model, list_incidents
from app.modules.incidents.workflow import create_delivered_incident
from app.modules.training.delivery import due_items, finalize_order
from app.modules.training.models import (
    DeliveryState,
    QueueMode,
    ScenarioQueueItem,
    TrainingGroup,
    TrainingMode,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
)


def test_group_delivery_is_one_card_for_all_members():
    now = datetime(2026, 9, 23, 12, tzinfo=UTC)
    runs = [
        TrainingRun(id=1, group_id=5, queue_mode=QueueMode.SHARED_QUEUE),
        TrainingRun(id=2, group_id=5, queue_mode=QueueMode.SHARED_QUEUE),
    ]
    group = TrainingGroup(id=5, queue_mode=QueueMode.SHARED_QUEUE)
    items = [
        ScenarioQueueItem(
            id=index, training_group_id=5, position=index, delivery_state=DeliveryState.PENDING
        )
        for index in (1, 2)
    ]
    session = TrainingSession(
        mode=TrainingMode.FLOW,
        state=TrainingSessionState.ACTIVE,
        runs=runs,
        groups=[group],
        queue_items=items,
        delivery_interval_seconds=120,
        delivery_checked_at=now,
        delivery_elapsed_seconds=0,
    )
    finalize_order(session)
    assert [item.id for item in due_items(session, now)] == [1]


def test_shared_card_is_visible_to_group_but_only_owner_can_act():
    owner = User(id=1, username="owner", full_name="Иванов", role=UserRole.TRAINEE)
    colleague = User(id=2, username="colleague", full_name="Петров", role=UserRole.TRAINEE)
    outsider = User(id=3, username="outsider", full_name="Сидоров", role=UserRole.TRAINEE)
    runs = [
        TrainingRun(
            id=11,
            trainee=owner,
            trainee_id=1,
            group_id=5,
            queue_mode=QueueMode.SHARED_QUEUE,
            workstation_number=5,
        ),
        TrainingRun(
            id=12,
            trainee=colleague,
            trainee_id=2,
            group_id=5,
            queue_mode=QueueMode.SHARED_QUEUE,
            workstation_number=6,
        ),
        TrainingRun(
            id=13,
            trainee=outsider,
            trainee_id=3,
            group_id=6,
            queue_mode=QueueMode.SHARED_QUEUE,
            workstation_number=7,
        ),
    ]
    session = TrainingSession(id=10, state=TrainingSessionState.ACTIVE, runs=runs)
    incident = create_delivered_incident(
        training_session_id=10,
        source_snapshot={
            "incident_number": "КП-1001",
            "reported_at": datetime.now(UTC).isoformat(),
            "source": "Система-112",
            "address": "Учебный объект",
            "description": "Проверка",
            "incident_type": "Проверка",
        },
    )
    incident.training_session = session
    incident.training_group_id = 5
    incident.id = 101
    incident.actions[0].id = 1

    _ensure_incident_visible(incident, colleague)
    assert _to_read_model(incident, colleague).can_claim is True
    assert _to_read_model(incident, colleague).available_actions == []
    with pytest.raises(HTTPException) as error:
        _ensure_incident_visible(incident, outsider)
    assert error.value.status_code == 404

    incident.claimed_by_training_run_id = runs[0].id
    incident.training_run = runs[0]
    assert _to_read_model(incident, owner).can_edit is True
    colleague_view = _to_read_model(incident, colleague)
    assert colleague_view.can_claim is False
    assert colleague_view.can_edit is False
    assert colleague_view.claimant_name == "Иванов"
    assert colleague_view.claimant_workstation_number == 5


def test_trainee_list_query_compiles_with_group_membership():
    """Подзапрос группы не должен потерять FROM при корреляции с внешним TrainingRun."""
    statements = []
    database = MagicMock()

    async def capture(statement):
        statements.append(statement)
        result = MagicMock()
        result.unique.return_value.all.return_value = []
        return result

    database.scalars = AsyncMock(side_effect=capture)
    user = User(id=3, username="trainee", role=UserRole.TRAINEE)
    assert asyncio.run(list_incidents(user, database)) == []
    sql = str(statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "FROM training_runs AS training_runs_1" in sql
    assert "training_runs_1.training_session_id = incidents.training_session_id" in sql
