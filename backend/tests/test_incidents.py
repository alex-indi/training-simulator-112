"""Проверки базовой карточки происшествия и её API-команд."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import IncidentLifecycleState
from app.modules.incidents.router import create_incident, read_incident
from app.modules.incidents.schemas import IncidentCreate, IncidentSnapshot
from app.modules.incidents.workflow import create_delivered_incident
from app.modules.training.models import TrainingSession, TrainingSessionState


def make_snapshot() -> IncidentSnapshot:
    """Возвращает реалистичный минимум готовой карточки Virtual112."""
    return IncidentSnapshot(
        incident_number="112-2026-0007",
        reported_at=datetime(2026, 9, 22, 8, 45, tzinfo=UTC),
        source="Система-112",
        applicant_name="Иван Петров",
        applicant_phone="+79990000000",
        address="Москва, ул. Учебная, д. 7",
        latitude=55.7558,
        longitude=37.6176,
        description="Запах дыма в подъезде",
        features=["дым", "жилой дом"],
        incident_type="Пожар",
        notified_services=["ДДС пожарной охраны"],
        scenario_event_key="initial_incident",
    )


def test_incident_lifecycle_has_independent_domain_states() -> None:
    """Lifecycle карточки не подменяет будущие статусы реагирования ДДС."""
    assert list(IncidentLifecycleState) == [
        IncidentLifecycleState.CREATED,
        IncidentLifecycleState.DELIVERED,
        IncidentLifecycleState.OPENED,
        IncidentLifecycleState.FINISHED,
    ]


def test_delivered_incident_uses_server_time_and_snapshot_copy() -> None:
    """Доставка фиксирует серверное время и не хранит ссылку на данные сценария."""
    server_time = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
    source_snapshot = make_snapshot().model_dump(mode="json")

    incident = create_delivered_incident(
        training_session_id=12,
        source_snapshot=source_snapshot,
        server_time=server_time,
    )
    source_snapshot["features"].append("изменено после доставки")

    assert incident.training_session_id == 12
    assert incident.lifecycle_state == IncidentLifecycleState.DELIVERED
    assert incident.created_at == server_time
    assert incident.delivered_at == server_time
    assert incident.opened_at is None
    assert incident.primary_status_at is None
    assert incident.source_snapshot["features"] == ["дым", "жилой дом"]
    assert incident.source_snapshot["scenario_event_key"] == "initial_incident"


def test_snapshot_rejects_invalid_coordinates() -> None:
    """API не принимает физически невозможные координаты карточки."""
    data = make_snapshot().model_dump()
    data["latitude"] = 91

    with pytest.raises(ValueError):
        IncidentSnapshot.model_validate(data)


def test_only_instructor_can_deliver_incident() -> None:
    """Обучаемый не может сам создать входящую карточку."""
    trainee = User(
        id=3,
        username="trainee",
        full_name="Диспетчер ДДС",
        role=UserRole.TRAINEE,
    )
    database = MagicMock()

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            create_incident(
                payload=IncidentCreate(
                    training_session_id=12,
                    source_snapshot=make_snapshot(),
                ),
                current_user=trainee,
                database=database,
            )
        )

    assert error.value.status_code == 403
    database.add.assert_not_called()


def test_instructor_delivers_incident_to_active_owned_session() -> None:
    """Команда доставки сохраняет snapshot в активной сессии преподавателя."""
    instructor = User(
        id=2,
        username="instructor",
        full_name="Преподаватель",
        role=UserRole.INSTRUCTOR,
    )
    training_session = TrainingSession(
        id=12,
        title="Учебная смена",
        instructor_id=instructor.id,
        state=TrainingSessionState.ACTIVE,
        trainees=[],
    )
    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = training_session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=scalar_result)
    database.commit = AsyncMock()
    database.add.side_effect = lambda incident: setattr(incident, "id", 7)

    response = asyncio.run(
        create_incident(
            payload=IncidentCreate(
                training_session_id=training_session.id,
                source_snapshot=make_snapshot(),
            ),
            current_user=instructor,
            database=database,
        )
    )

    assert response.id == 7
    assert response.training_session_id == training_session.id
    assert response.lifecycle_state == IncidentLifecycleState.DELIVERED
    assert response.delivered_at is not None
    assert response.source_snapshot.model_extra == {
        "scenario_event_key": "initial_incident"
    }
    database.commit.assert_awaited_once()


def test_assigned_trainee_can_restore_incident_from_api() -> None:
    """GET возвращает назначенному обучаемому сохранённую карточку и snapshot."""
    trainee = User(
        id=3,
        username="trainee",
        full_name="Диспетчер ДДС",
        role=UserRole.TRAINEE,
    )
    training_session = TrainingSession(
        id=12,
        title="Учебная смена",
        instructor_id=2,
        state=TrainingSessionState.ACTIVE,
        trainees=[trainee],
    )
    incident = create_delivered_incident(
        training_session_id=training_session.id,
        source_snapshot=make_snapshot().model_dump(mode="json"),
        server_time=datetime(2026, 9, 22, 9, 0, tzinfo=UTC),
    )
    incident.id = 7
    incident.training_session = training_session
    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = incident
    database = MagicMock()
    database.scalars = AsyncMock(return_value=scalar_result)

    response = asyncio.run(
        read_incident(
            incident_id=incident.id,
            current_user=trainee,
            database=database,
        )
    )

    assert response.id == incident.id
    assert response.source_snapshot.features == ["дым", "жилой дом"]
    assert response.source_snapshot.notified_services == ["ДДС пожарной охраны"]
