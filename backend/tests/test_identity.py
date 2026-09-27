"""Проверки пользователей и ролей локального стенда."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.identity.router import claim_workstation, heartbeat_workstation
from app.modules.identity.schemas import WorkstationClaim


def test_user_roles_are_centralized() -> None:
    """Централизованный enum содержит только роли первого MVP."""
    assert list(UserRole) == [
        UserRole.ADMIN,
        UserRole.INSTRUCTOR,
        UserRole.TRAINEE,
    ]


def test_current_user_defaults_to_trainee() -> None:
    """Запрос без demo-заголовка выбирает обучаемого из базы данных."""
    session = AsyncMock()
    scalar_result = MagicMock()
    expected_user = User(
        id=3,
        username="trainee",
        full_name="Диспетчер ДДС",
        role=UserRole.TRAINEE,
    )
    scalar_result.one_or_none.return_value = expected_user
    session.scalars.return_value = scalar_result

    user = asyncio.run(get_current_user(session=session, demo_username=None))

    assert user is expected_user
    session.scalars.assert_awaited_once()


def test_unknown_demo_user_is_rejected() -> None:
    """Неизвестное локальное имя не превращается в произвольную роль."""
    session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.one_or_none.return_value = None
    session.scalars.return_value = scalar_result

    with pytest.raises(HTTPException) as error:
        asyncio.run(get_current_user(session=session, demo_username="unknown"))

    assert error.value.status_code == 404


def test_trainee_claims_workstation_without_a_training_session() -> None:
    user = User(id=4, username="sid", full_name="Сидоров", role=UserRole.TRAINEE)
    database = AsyncMock()
    database.scalar.return_value = None

    presence = asyncio.run(
        claim_workstation(WorkstationClaim(workstation_number=12), user, database)
    )

    assert presence.workstation_number == 12
    assert presence.user_id == user.id
    database.commit.assert_awaited_once()


def test_online_workstation_cannot_be_claimed_by_another_trainee() -> None:
    user = User(id=4, username="sid", full_name="Сидоров", role=UserRole.TRAINEE)
    occupant = User(
        id=5, username="trainee", full_name="Обучаемый", role=UserRole.TRAINEE,
        workstation_number=12, workstation_last_seen_at=datetime.now(UTC),
    )
    database = AsyncMock()
    database.scalar.return_value = occupant

    with pytest.raises(HTTPException) as error:
        asyncio.run(claim_workstation(WorkstationClaim(workstation_number=12), user, database))

    assert error.value.status_code == 409
    database.commit.assert_not_awaited()


def test_workstation_heartbeat_is_independent_of_training_run() -> None:
    user = User(
        id=4, username="sid", full_name="Сидоров", role=UserRole.TRAINEE,
        workstation_number=12,
    )
    database = AsyncMock()

    asyncio.run(heartbeat_workstation(user, database))

    assert user.workstation_last_seen_at is not None
    database.commit.assert_awaited_once()
