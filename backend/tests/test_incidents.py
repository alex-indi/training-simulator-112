"""Проверки базовой карточки происшествия и её API-команд."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import (
    DDSResponseStatus,
    DdsServiceEventType,
    IncidentActionType,
    IncidentLifecycleState,
)
from app.modules.incidents.router import (
    change_incident_status,
    create_incident,
    open_incident,
    read_incident,
)
from app.modules.incidents.schemas import (
    IncidentActionCreate,
    IncidentCreate,
    IncidentSnapshot,
)
from app.modules.incidents.workflow import (
    IncidentActionCommentRequiredError,
    InvalidIncidentTransitionError,
    create_delivered_incident,
    get_available_actions,
    mark_incident_opened,
    perform_incident_action,
)
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


def assign_persisted_ids(incident, *, incident_id: int = 7) -> None:
    """Имитирует выдачу PostgreSQL-id агрегату в unit-тестах router."""
    incident.id = incident_id
    for action_id, action in enumerate(incident.actions, start=1):
        action.id = action_id
        action.incident_id = incident_id


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
    assert len(incident.actions) == 1
    assert incident.actions[0].status == DdsServiceEventType.SERVICE_ADDED
    assert incident.actions[0].created_at == server_time
    assert incident.actions[0].is_system is True


def test_snapshot_rejects_invalid_coordinates() -> None:
    """API не принимает физически невозможные координаты карточки."""
    data = make_snapshot().model_dump()
    data["latitude"] = 91

    with pytest.raises(ValueError):
        IncidentSnapshot.model_validate(data)

def test_open_incident_is_idempotent_and_uses_first_server_time() -> None:
    """Повторное открытие не переписывает время первого просмотра карточки."""
    incident = create_delivered_incident(
        training_session_id=12,
        source_snapshot=make_snapshot().model_dump(mode="json"),
        server_time=datetime(2026, 9, 22, 9, 0, tzinfo=UTC),
    )
    first_opened_at = datetime(2026, 9, 22, 9, 5, tzinfo=UTC)

    mark_incident_opened(incident, server_time=first_opened_at)
    mark_incident_opened(
        incident,
        server_time=datetime(2026, 9, 22, 9, 10, tzinfo=UTC),
    )

    assert incident.lifecycle_state == IncidentLifecycleState.OPENED
    assert incident.opened_at == first_opened_at
    assert [action.status for action in incident.actions] == [
        DdsServiceEventType.SERVICE_ADDED,
        DdsServiceEventType.SERVICE_RECEIVED,
    ]


def test_primary_decision_requires_comment_and_preserves_rejection_history() -> None:
    """Не принята требует причину, а последующая Принята не стирает отказ."""
    delivered_at = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
    rejected_at = datetime(2026, 9, 22, 9, 0, 24, tzinfo=UTC)
    accepted_at = datetime(2026, 9, 22, 9, 1, tzinfo=UTC)
    incident = create_delivered_incident(
        training_session_id=12,
        source_snapshot=make_snapshot().model_dump(mode="json"),
        server_time=delivered_at,
    )
    incident.id = 7

    assert get_available_actions(incident) == [
        IncidentActionType.ACCEPT,
        IncidentActionType.REJECT,
    ]
    with pytest.raises(IncidentActionCommentRequiredError):
        perform_incident_action(
            incident,
            action=IncidentActionType.REJECT,
            actor_user_id=3,
            actor_display_name="Диспетчер ДДС",
            comment="   ",
            server_time=rejected_at,
        )

    perform_incident_action(
        incident,
        action=IncidentActionType.REJECT,
        actor_user_id=3,
        actor_display_name="Диспетчер ДДС",
        comment=" Дубль, реагирование по КП №42 ",
        server_time=rejected_at,
    )
    assert incident.dds_status == DDSResponseStatus.REJECTED
    assert incident.primary_status_at == rejected_at
    assert (incident.primary_status_at - incident.delivered_at).total_seconds() == 24
    assert get_available_actions(incident) == [IncidentActionType.ACCEPT]

    perform_incident_action(
        incident,
        action=IncidentActionType.ACCEPT,
        actor_user_id=3,
        actor_display_name="Диспетчер ДДС",
        comment="Руководитель подтвердил реагирование",
        server_time=accepted_at,
    )

    manual_actions = [entry for entry in incident.actions if not entry.is_system]
    assert [entry.action for entry in manual_actions] == [
        IncidentActionType.REJECT,
        IncidentActionType.ACCEPT,
    ]
    assert manual_actions[0].comment == "Дубль, реагирование по КП №42"
    assert incident.primary_status_at == rejected_at


def test_after_accept_backend_allows_skipped_stages_once_until_terminal() -> None:
    """Backend сохраняет пропуски для Assessment, но запрещает дубли и финальные правки."""
    incident = create_delivered_incident(
        training_session_id=12,
        source_snapshot=make_snapshot().model_dump(mode="json"),
    )
    incident.id = 7
    perform_incident_action(
        incident,
        action=IncidentActionType.ACCEPT,
        actor_user_id=3,
        actor_display_name="Диспетчер ДДС",
    )

    assert get_available_actions(incident) == [
        IncidentActionType.START_RESPONSE,
        IncidentActionType.MARK_ARRIVAL,
        IncidentActionType.START_WORK,
        IncidentActionType.COMPLETE_WORK,
        IncidentActionType.REFUSE_WORK,
    ]
    perform_incident_action(
        incident,
        action=IncidentActionType.MARK_ARRIVAL,
        actor_user_id=3,
        actor_display_name="Диспетчер ДДС",
        comment="Прибыли на место",
    )
    assert incident.dds_status == DDSResponseStatus.ARRIVED
    assert IncidentActionType.START_RESPONSE in get_available_actions(incident)
    assert IncidentActionType.MARK_ARRIVAL not in get_available_actions(incident)

    with pytest.raises(InvalidIncidentTransitionError):
        perform_incident_action(
            incident,
            action=IncidentActionType.MARK_ARRIVAL,
            actor_user_id=3,
            actor_display_name="Диспетчер ДДС",
        )

    perform_incident_action(
        incident,
        action=IncidentActionType.COMPLETE_WORK,
        actor_user_id=3,
        actor_display_name="Диспетчер ДДС",
        comment="Работы завершены, пострадавших нет",
    )
    assert incident.dds_status == DDSResponseStatus.COMPLETED
    assert get_available_actions(incident) == []
    with pytest.raises(InvalidIncidentTransitionError):
        perform_incident_action(
            incident,
            action=IncidentActionType.START_WORK,
            actor_user_id=3,
            actor_display_name="Диспетчер ДДС",
        )


def test_refuse_work_is_available_after_accept_and_requires_comment() -> None:
    """Отказ от работ доступен сразу после Принята и закрывает редактирование."""
    incident = create_delivered_incident(
        training_session_id=12,
        source_snapshot=make_snapshot().model_dump(mode="json"),
    )
    incident.id = 7
    perform_incident_action(
        incident,
        action=IncidentActionType.ACCEPT,
        actor_user_id=3,
        actor_display_name="Диспетчер ДДС",
    )

    with pytest.raises(IncidentActionCommentRequiredError):
        perform_incident_action(
            incident,
            action=IncidentActionType.REFUSE_WORK,
            actor_user_id=3,
            actor_display_name="Диспетчер ДДС",
        )

    perform_incident_action(
        incident,
        action=IncidentActionType.REFUSE_WORK,
        actor_user_id=3,
        actor_display_name="Диспетчер ДДС",
        comment="Объект вне зоны ответственности, информация передана службе 101",
    )
    assert incident.dds_status == DDSResponseStatus.WORK_REFUSED
    assert get_available_actions(incident) == []


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
    database.add.side_effect = assign_persisted_ids

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
    assign_persisted_ids(incident)
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


def test_assigned_trainee_opens_incident_and_backend_commits_time() -> None:
    """Команда открытия сохраняет серверное время в доступной карточке."""
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
    assign_persisted_ids(incident)
    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = incident
    database = MagicMock()
    database.scalars = AsyncMock(return_value=scalar_result)
    database.commit = AsyncMock(side_effect=lambda: assign_persisted_ids(incident))

    response = asyncio.run(
        open_incident(
            incident_id=incident.id,
            current_user=trainee,
            database=database,
        )
    )

    assert response.lifecycle_state == IncidentLifecycleState.OPENED
    assert response.opened_at is not None
    assert [entry.status for entry in response.actions] == [
        DdsServiceEventType.SERVICE_ADDED,
        DdsServiceEventType.SERVICE_RECEIVED,
    ]
    database.commit.assert_awaited_once()


def test_assigned_trainee_changes_status_through_api() -> None:
    """API повторно проверяет доступность и возвращает сохранённую историю."""
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
    incident.training_session = training_session
    assign_persisted_ids(incident)
    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = incident
    database = MagicMock()
    database.scalars = AsyncMock(return_value=scalar_result)
    database.commit = AsyncMock(side_effect=lambda: assign_persisted_ids(incident))

    response = asyncio.run(
        change_incident_status(
            incident_id=incident.id,
            payload=IncidentActionCreate(
                action=IncidentActionType.REJECT,
                comment="Объект вне зоны ответственности",
            ),
            current_user=trainee,
            database=database,
        )
    )

    assert response.dds_status == DDSResponseStatus.REJECTED
    assert response.available_actions == [IncidentActionType.ACCEPT]
    assert response.primary_status_at is not None
    assert response.primary_response_duration_seconds is not None
    assert response.actions[-1].actor_user_id == trainee.id
    assert response.actions[-1].actor_display_name == trainee.full_name
    assert response.actions[-1].comment == "Объект вне зоны ответственности"
    database.commit.assert_awaited_once()


def test_unassigned_trainee_cannot_change_incident_status() -> None:
    """Назначение на другую сессию не даёт доступ к чужой карточке."""
    assigned_trainee = User(
        id=3,
        username="assigned",
        full_name="Назначенный диспетчер",
        role=UserRole.TRAINEE,
    )
    outsider = User(
        id=4,
        username="outsider",
        full_name="Другой диспетчер",
        role=UserRole.TRAINEE,
    )
    training_session = TrainingSession(
        id=12,
        title="Учебная смена",
        instructor_id=2,
        state=TrainingSessionState.ACTIVE,
        trainees=[assigned_trainee],
    )
    incident = create_delivered_incident(
        training_session_id=training_session.id,
        source_snapshot=make_snapshot().model_dump(mode="json"),
    )
    incident.training_session = training_session
    assign_persisted_ids(incident)
    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = incident
    database = MagicMock()
    database.scalars = AsyncMock(return_value=scalar_result)
    database.commit = AsyncMock()

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            change_incident_status(
                incident_id=incident.id,
                payload=IncidentActionCreate(action=IncidentActionType.ACCEPT),
                current_user=outsider,
                database=database,
            )
        )

    assert error.value.status_code == 404
    database.commit.assert_not_awaited()


def test_instructor_cannot_mark_incident_as_opened_by_trainee() -> None:
    """Просмотр преподавателя не подменяет факт открытия обучаемым."""
    instructor = User(
        id=2,
        username="instructor",
        full_name="Преподаватель",
        role=UserRole.INSTRUCTOR,
    )
    database = MagicMock()

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            open_incident(
                incident_id=7,
                current_user=instructor,
                database=database,
            )
        )

    assert error.value.status_code == 403
    database.commit.assert_not_called()
