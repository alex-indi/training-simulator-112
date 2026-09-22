"""Проверки пользователей и ролей локального стенда."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole


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
