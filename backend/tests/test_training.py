"""Проверки модели и переходов базовой учебной сессии."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.training.models import (
    DeliveryOrder,
    QueueMode,
    ScenarioQueueItem,
    TrainingGroup,
    TrainingMode,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
)
from app.modules.training.router import (
    _readiness,
    archive_training_session,
    assign_runs,
    create_group,
    create_training_session,
    heartbeat,
    list_training_sessions,
    prepare_session,
    start_session,
)
from app.modules.training.schemas import (
    BulkAssignment,
    GroupWrite,
    TemplateCreate,
    TrainingSessionCreate,
)
from app.modules.training.workflow import (
    InvalidTrainingSessionTransitionError,
    prepare_training_session,
    start_training_session,
)


def make_training_session() -> TrainingSession:
    """Создаёт минимальную сессию с назначенным обучаемым без базы данных."""
    trainee = User(
        id=3,
        username="trainee",
        full_name="Диспетчер ДДС",
        role=UserRole.TRAINEE,
    )
    return TrainingSession(
        id=1,
        title="Учебная смена № 1",
        instructor_id=2,
        state=TrainingSessionState.DRAFT,
        trainees=[trainee],
        runs=[
            TrainingRun(
                id=1,
                trainee_id=3,
                trainee=trainee,
                dds_profile="ДДС района",
                queue_mode=QueueMode.INDIVIDUAL_QUEUE,
                workstation_number=1,
            )
        ],
        groups=[],
        mode=TrainingMode.MANUAL,
        delivery_order=DeliveryOrder.SEQUENTIAL,
        workstation_count=30,
    )


def test_training_session_state_has_domain_states() -> None:
    """Enum сохраняет полный набор состояний согласованной state machine."""
    assert list(TrainingSessionState) == [
        TrainingSessionState.DRAFT,
        TrainingSessionState.READY,
        TrainingSessionState.ACTIVE,
        TrainingSessionState.COMPLETED,
        TrainingSessionState.CANCELLED,
    ]


def test_training_session_is_prepared_and_started_with_server_time() -> None:
    """Допустимый flow переводит DRAFT → READY → ACTIVE и фиксирует время."""
    training_session = make_training_session()
    server_time = datetime(2026, 9, 22, 9, 15, tzinfo=UTC)

    prepare_training_session(training_session)
    start_training_session(training_session, server_time=server_time)

    assert training_session.state == TrainingSessionState.ACTIVE
    assert training_session.started_at == server_time


def test_training_session_cannot_start_from_draft() -> None:
    """Backend не обходит обязательную подготовку сессии."""
    training_session = make_training_session()

    with pytest.raises(InvalidTrainingSessionTransitionError):
        start_training_session(training_session)

    assert training_session.state == TrainingSessionState.DRAFT
    assert training_session.started_at is None


def test_training_session_requires_unique_trainees() -> None:
    """Один обучаемый не назначается в сессию повторно."""
    with pytest.raises(ValueError):
        TrainingSessionCreate(title="Смена", trainee_ids=[3, 3])


@pytest.mark.parametrize("payload", [
    lambda: GroupWrite(name="   "),
    lambda: GroupWrite(name="Группа", dds_profile="   "),
    lambda: TemplateCreate(name="   ", training_session_id=1),
])
def test_required_names_reject_whitespace(payload) -> None:
    with pytest.raises(ValueError):
        payload()


def test_only_instructor_can_create_training_session() -> None:
    """Обучаемый не может вызвать преподавательскую команду создания."""
    trainee = User(
        id=3,
        username="trainee",
        full_name="Диспетчер ДДС",
        role=UserRole.TRAINEE,
    )
    database = MagicMock()

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            create_training_session(
                payload=TrainingSessionCreate(title="Смена", trainee_ids=[3]),
                current_user=trainee,
                database=database,
            )
        )

    assert error.value.status_code == 403
    database.add.assert_not_called()


def test_instructor_start_command_persists_active_session() -> None:
    """REST-команда запуска применяет переход и сохраняет серверное время."""
    instructor = User(
        id=2,
        username="instructor",
        full_name="Преподаватель",
        role=UserRole.INSTRUCTOR,
    )
    training_session = make_training_session()
    training_session.state = TrainingSessionState.READY
    training_session.created_at = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)

    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = training_session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=scalar_result)
    database.commit = AsyncMock()

    response = asyncio.run(
        start_session(
            training_session_id=training_session.id,
            current_user=instructor,
            database=database,
        )
    )

    assert response.state == TrainingSessionState.ACTIVE
    assert response.started_at is not None
    assert response.started_at.tzinfo is not None
    database.commit.assert_awaited_once()


def test_instructor_can_archive_inactive_session() -> None:
    instructor = User(
        id=2,
        username="instructor",
        full_name="Преподаватель",
        role=UserRole.INSTRUCTOR,
    )
    training_session = make_training_session()
    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = training_session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=scalar_result)
    database.commit = AsyncMock()

    asyncio.run(archive_training_session(training_session.id, instructor, database))

    assert training_session.is_archived is True
    database.commit.assert_awaited_once()


def test_active_session_cannot_be_archived() -> None:
    instructor = User(
        id=2,
        username="instructor",
        full_name="Преподаватель",
        role=UserRole.INSTRUCTOR,
    )
    training_session = make_training_session()
    training_session.state = TrainingSessionState.ACTIVE
    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = training_session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=scalar_result)
    database.commit = AsyncMock()

    with pytest.raises(HTTPException) as error:
        asyncio.run(archive_training_session(training_session.id, instructor, database))

    assert error.value.status_code == 409
    database.commit.assert_not_awaited()


def test_offline_participant_warns_without_blocking_start() -> None:
    session = make_training_session()
    readiness = _readiness(session)
    assert readiness.can_start is True
    assert readiness.offline_count == 1
    assert "Offline: 1" in readiness.warnings


def test_preassigned_trainee_must_join_before_start() -> None:
    session = make_training_session()
    session.runs = []
    readiness = _readiness(session)
    assert readiness.can_start is False
    assert "Не все назначенные обучаемые заняли АРМ" in readiness.warnings


def test_empty_session_cannot_be_prepared() -> None:
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = make_training_session()
    session.runs = []
    result = MagicMock()
    result.one_or_none.return_value = session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as error:
        asyncio.run(prepare_session(session.id, instructor, database))

    assert error.value.status_code == 409
    assert session.state == TrainingSessionState.DRAFT
    database.commit.assert_not_called()


def test_group_cannot_change_after_session_start() -> None:
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = make_training_session()
    session.state = TrainingSessionState.ACTIVE
    result = MagicMock()
    result.one_or_none.return_value = session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as error:
        asyncio.run(create_group(session.id, GroupWrite(name="Группа 1"), instructor, database))

    assert error.value.status_code == 409
    assert session.groups == []
    database.commit.assert_not_called()


def test_group_assignment_copies_all_group_parameters() -> None:
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = make_training_session()
    session.created_at = datetime(2026, 9, 24, tzinfo=UTC)
    session.groups = [TrainingGroup(
        id=4, name="Пожарная охрана", dds_profile="Пожарная охрана",
        difficulty="Высокая", queue_mode=QueueMode.SHARED_QUEUE,
    )]
    session.queue_items = []
    result = MagicMock()
    result.one_or_none.return_value = session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=result)
    database.commit = AsyncMock()

    response = asyncio.run(assign_runs(
        session.id, BulkAssignment(run_ids=[1], group_id=4), instructor, database,
    ))

    assert response.runs[0].group_id == 4
    assert response.runs[0].dds_profile == "Пожарная охрана"
    assert response.runs[0].difficulty == "Высокая"
    assert response.runs[0].queue_mode == QueueMode.SHARED_QUEUE
    database.commit.assert_awaited_once()


def test_group_assignment_rejects_individual_override() -> None:
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = make_training_session()
    session.groups = [TrainingGroup(id=4, name="Группа", queue_mode=QueueMode.SHARED_QUEUE)]
    result = MagicMock()
    result.one_or_none.return_value = session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=result)
    database.commit = AsyncMock()

    with pytest.raises(HTTPException) as error:
        asyncio.run(assign_runs(
            session.id,
            BulkAssignment(run_ids=[1], group_id=4, queue_mode=QueueMode.INDIVIDUAL_QUEUE),
            instructor, database,
        ))
    assert error.value.status_code == 422
    assert session.runs[0].group_id is None
    database.commit.assert_not_awaited()


def test_fixed_set_needs_approved_item_for_every_target() -> None:
    session = make_training_session()
    second = User(id=4, username="second", full_name="Второй", role=UserRole.TRAINEE)
    session.trainees.append(second)
    session.runs.append(TrainingRun(
        id=2, trainee_id=4, trainee=second, dds_profile="ДДС района",
        queue_mode=QueueMode.INDIVIDUAL_QUEUE, workstation_number=2,
    ))
    session.mode = TrainingMode.FIXED_SET
    session.queue_items = [ScenarioQueueItem(training_run_id=1, approved=True)]
    assert _readiness(session).can_start is False
    session.queue_items.append(ScenarioQueueItem(training_run_id=2, approved=True))
    assert _readiness(session).can_start is True


def test_group_change_invalidates_ready_state() -> None:
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = make_training_session()
    session.state = TrainingSessionState.READY
    session.created_at = datetime(2026, 9, 24, tzinfo=UTC)
    session.queue_items = []
    result = MagicMock()
    result.one_or_none.return_value = session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=result)
    database.commit = AsyncMock(side_effect=lambda: setattr(session.groups[0], "id", 4))

    asyncio.run(create_group(
        session.id, GroupWrite(name="Новая группа"), instructor, database,
    ))
    assert session.state == TrainingSessionState.DRAFT
    database.commit.assert_awaited_once()


def test_bulk_assignment_invalidates_ready_state() -> None:
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = make_training_session()
    session.state = TrainingSessionState.READY
    session.created_at = datetime(2026, 9, 24, tzinfo=UTC)
    session.queue_items = []
    result = MagicMock()
    result.one_or_none.return_value = session
    database = MagicMock()
    database.scalars = AsyncMock(return_value=result)
    database.commit = AsyncMock()

    asyncio.run(assign_runs(
        session.id, BulkAssignment(run_ids=[1], dds_profile="ДДС района"),
        instructor, database,
    ))
    assert session.state == TrainingSessionState.DRAFT
    database.commit.assert_awaited_once()


def test_trainee_lobby_returns_only_summary_without_queue() -> None:
    trainee = User(id=3, username="trainee", role=UserRole.TRAINEE)
    session = make_training_session()
    session.queue_items = [ScenarioQueueItem(training_run_id=1, approved=True)]
    result = MagicMock()
    result.all.return_value = [(session, session.runs[0])]
    database = MagicMock()
    database.execute = AsyncMock(return_value=result)

    summaries = asyncio.run(list_training_sessions(trainee, database))

    assert len(summaries) == 1
    assert summaries[0].own_run.id == 1
    assert "runs" not in summaries[0].model_dump()
    assert "queue_items" not in summaries[0].model_dump()


def test_heartbeat_commits_without_loading_full_session() -> None:
    trainee = User(id=3, username="trainee", role=UserRole.TRAINEE)
    result = MagicMock()
    result.rowcount = 1
    database = MagicMock()
    database.execute = AsyncMock(return_value=result)
    database.commit = AsyncMock()

    assert asyncio.run(heartbeat(1, trainee, database)) is None
    database.execute.assert_awaited_once()
    database.commit.assert_awaited_once()
    database.scalars.assert_not_called()
