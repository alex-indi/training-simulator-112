"""Critical authorization and safety checks for the admin boundary."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.main import app
from app.modules.admin.dependencies import require_admin
from app.modules.admin.models import AdminAudit
from app.modules.admin.router import update_user
from app.modules.admin.schemas import AIConfigRead, UserUpdate
from app.modules.identity.models import User, UserRole
from app.modules.object_registry.models import ObjectType


def make_user(user_id: int, role: UserRole, *, active: bool = True) -> User:
    return User(
        id=user_id,
        username=f"user-{user_id}",
        full_name=f"Пользователь {user_id}",
        role=role,
        is_active=active,
    )


@pytest.mark.parametrize("role", [UserRole.INSTRUCTOR, UserRole.TRAINEE])
def test_non_admin_roles_cannot_enter_admin_boundary(role: UserRole) -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_admin(make_user(2, role)))

    assert error.value.status_code == 403


def test_admin_can_enter_admin_boundary() -> None:
    admin = make_user(1, UserRole.ADMIN)

    assert asyncio.run(require_admin(admin)) is admin


def test_last_active_admin_cannot_be_deactivated() -> None:
    admin = make_user(1, UserRole.ADMIN)
    session = AsyncMock()
    session.get.return_value = admin
    session.scalar.return_value = 1

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            update_user(
                user_id=admin.id,
                payload=UserUpdate(is_active=False),
                session=session,
                admin=admin,
            )
        )

    assert error.value.status_code == 409
    assert admin.is_active is True
    session.commit.assert_not_awaited()


def test_admin_can_deactivate_user_and_action_is_audited() -> None:
    admin = make_user(1, UserRole.ADMIN)
    trainee = make_user(3, UserRole.TRAINEE)
    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = trainee

    result = asyncio.run(
        update_user(
            user_id=trainee.id,
            payload=UserUpdate(is_active=False),
            session=session,
            admin=admin,
        )
    )

    assert result.is_active is False
    audit = session.add.call_args.args[0]
    assert isinstance(audit, AdminAudit)
    assert audit.action == "USER_ACTIVATION_CHANGED"
    assert audit.before["is_active"] is True
    assert audit.after["is_active"] is False
    session.commit.assert_awaited_once()


def test_ai_contract_never_contains_secret_value() -> None:
    fields = AIConfigRead.model_fields

    assert "api_key" not in fields
    assert "api_key_configured" in fields


def test_source_driven_catalogues_have_no_create_endpoint() -> None:
    methods_by_path = app.openapi()["paths"]

    assert set(methods_by_path["/api/admin/classifier"]) == {"get"}
    assert set(methods_by_path["/api/admin/services"]) == {"get"}
    assert set(methods_by_path["/api/admin/object-registry"]) == {"get"}
    assert "object_types" in ObjectType.__tablename__
