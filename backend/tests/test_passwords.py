"""Password hashing contract for locally managed users."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.identity.models import User, UserRole
from app.modules.identity.passwords import hash_password, verify_password
from app.modules.identity.router import login
from app.modules.identity.schemas import UserLogin


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("training-secret")
    second = hash_password("training-secret")

    assert first != second
    assert "training-secret" not in first
    assert verify_password("training-secret", first)
    assert not verify_password("wrong-secret", first)


def session_with(user: User) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = user
    session.scalars.return_value = result
    return session


def test_login_accepts_managed_password() -> None:
    user = User(
        id=4,
        username="managed",
        full_name="Управляемый пользователь",
        role=UserRole.TRAINEE,
        is_active=True,
        password_hash=hash_password("training-secret"),
    )

    authenticated = asyncio.run(
        login(UserLogin(username="managed", password="training-secret"), session_with(user))
    )

    assert authenticated is user


def test_login_rejects_wrong_managed_password() -> None:
    user = User(
        id=4,
        username="managed",
        full_name="Управляемый пользователь",
        role=UserRole.TRAINEE,
        is_active=True,
        password_hash=hash_password("training-secret"),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            login(
                UserLogin(username="managed", password="wrong-secret"),
                session_with(user),
            )
        )

    assert error.value.status_code == 401
