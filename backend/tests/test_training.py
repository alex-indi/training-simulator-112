"""Проверки модели и переходов базовой учебной сессии."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.training.models import TrainingSession, TrainingSessionState
from app.modules.training.router import create_training_session, start_session
from app.modules.training.schemas import TrainingSessionCreate
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
