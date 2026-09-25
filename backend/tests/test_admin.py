"""Critical authorization and safety checks for the admin boundary."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.main import app
from app.modules.admin.dependencies import require_admin
from app.modules.admin.models import AdminAudit, AIProviderConfig, UserGroup
from app.modules.admin.router import (
    _deserialize_object_attribute,
    ai_health,
    ai_models,
    create_user,
    create_user_group,
    delete_user,
    delete_user_group,
    get_ai,
    update_ai,
    update_user,
    update_user_group,
)
from app.modules.admin.schemas import (
    AIConfigRead,
    AIConfigUpdate,
    AIModelCatalogRequest,
    UserCreate,
    UserGroupCreate,
    UserGroupUpdate,
    UserUpdate,
)
from app.modules.admin.secrets import decrypt_api_key
from app.modules.identity.models import User, UserRole
from app.modules.identity.passwords import verify_password
from app.modules.object_registry.models import ObjectType
from app.services.text_generation.providers import OpenAICompatibleProvider
from app.services.text_generation.renderer import ProviderHealth


def make_user(user_id: int, role: UserRole, *, active: bool = True) -> User:
    return User(
        id=user_id,
        username=f"user-{user_id}",
        full_name=f"Пользователь {user_id}",
        role=role,
        is_active=active,
    )


@pytest.mark.parametrize(
    ("value_type", "value", "expected"),
    [
        (
            "json",
            '[{"DayWeek": "понедельник", "WorkHours": "круглосуточно"}]',
            [{"DayWeek": "понедельник", "WorkHours": "круглосуточно"}],
        ),
        ("boolean", "true", True),
        ("integer", "3", 3),
        ("text", "Больница", "Больница"),
    ],
)
def test_object_attribute_values_are_deserialized_by_declared_type(
    value_type: str, value: str, expected: object
) -> None:
    attribute = MagicMock(value_type=value_type, value=value)

    assert _deserialize_object_attribute(attribute) == expected


@pytest.mark.parametrize("role", [UserRole.INSTRUCTOR, UserRole.TRAINEE])
def test_non_admin_roles_cannot_enter_admin_boundary(role: UserRole) -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_admin(make_user(2, role)))

    assert error.value.status_code == 403


def test_admin_can_enter_admin_boundary() -> None:
    admin = make_user(1, UserRole.ADMIN)

    assert asyncio.run(require_admin(admin)) is admin


def test_admin_ai_health_checks_provider_when_renderer_is_disabled(monkeypatch) -> None:
    async def available(provider) -> ProviderHealth:
        assert provider.base_url == "http://local.test/v1"
        assert provider.model == "local-test"
        return ProviderHealth("AVAILABLE", provider.name, provider.model)

    monkeypatch.setattr(OpenAICompatibleProvider, "healthcheck", available)
    session = AsyncMock()
    session.get.return_value = AIProviderConfig(
        id=1,
        provider="OPENAI_COMPATIBLE",
        model="local-test",
        base_url="http://local.test/v1",
        enabled=False,
        timeout_seconds=7,
    )
    result = asyncio.run(ai_health(session))
    assert result == {
        "status": "AVAILABLE",
        "available": True,
        "provider": "openai_compatible",
        "model": "local-test",
        "renderer_enabled": False,
    }


def test_reading_ai_defaults_does_not_create_saved_override() -> None:
    session = AsyncMock()
    session.get.return_value = None
    config = asyncio.run(get_ai(session))
    assert config.provider == "OPENAI"
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_admin_can_load_models_from_compatible_provider(monkeypatch) -> None:
    async def fake_list_models(provider: OpenAICompatibleProvider) -> list[str]:
        assert provider.base_url == "http://local.test/v1"
        return ["model-a", "model-b"]

    monkeypatch.setattr(OpenAICompatibleProvider, "list_models", fake_list_models)
    session = AsyncMock()
    session.get.return_value = None
    result = asyncio.run(
        ai_models(
            AIModelCatalogRequest(
                provider="OPENAI_COMPATIBLE",
                base_url="http://local.test/v1",
            ),
            session=session,
        )
    )

    assert result.models == ["model-a", "model-b"]


def test_admin_can_store_write_only_ai_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.modules.admin.secrets.KEY_PATH", tmp_path / "ai-provider.key")
    admin = make_user(1, UserRole.ADMIN)
    config = AIProviderConfig(
        id=1,
        provider="OPENAI_COMPATIBLE",
        model="model-a",
        base_url="http://local.test/v1",
        enabled=True,
        timeout_seconds=30,
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = config

    result = asyncio.run(
        update_ai(
            AIConfigUpdate(
                provider="OPENAI_COMPATIBLE",
                model="model-a",
                base_url="http://local.test/v1",
                enabled=True,
                timeout_seconds=30,
                api_key="provider-secret",
            ),
            session=session,
            admin=admin,
        )
    )

    assert result.api_key_configured is True
    assert "api_key" not in result.model_dump()
    assert decrypt_api_key(config.api_key_encrypted) == "provider-secret"
    audit = session.add.call_args.args[0]
    assert "api_key" not in audit.before
    assert "api_key" not in audit.after


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


def test_admin_can_change_login_name_and_password_without_auditing_secret() -> None:
    admin = make_user(1, UserRole.ADMIN)
    trainee = make_user(3, UserRole.TRAINEE)
    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = trainee
    session.scalar.return_value = None

    result = asyncio.run(
        update_user(
            user_id=trainee.id,
            payload=UserUpdate(
                username="dispatcher-2",
                full_name="Второй диспетчер",
                password="new-training-secret",
            ),
            session=session,
            admin=admin,
        )
    )

    assert result.username == "dispatcher-2"
    assert result.full_name == "Второй диспетчер"
    assert verify_password("new-training-secret", result.password_hash)
    audit = session.add.call_args.args[0]
    assert audit.action == "USER_CREDENTIALS_CHANGED"
    assert "password" not in audit.before
    assert "password" not in audit.after


def test_admin_cannot_reuse_existing_login() -> None:
    admin = make_user(1, UserRole.ADMIN)
    trainee = make_user(3, UserRole.TRAINEE)
    session = AsyncMock()
    session.get.return_value = trainee
    session.scalar.return_value = 2

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            update_user(
                user_id=trainee.id,
                payload=UserUpdate(username="instructor"),
                session=session,
                admin=admin,
            )
        )

    assert error.value.status_code == 409
    session.commit.assert_not_awaited()


def test_admin_created_user_gets_hashed_password_without_audit_secret() -> None:
    admin = make_user(1, UserRole.ADMIN)
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = None
    payload = UserCreate(
        username="new-trainee",
        full_name="Новый диспетчер",
        role=UserRole.TRAINEE,
        password="training-secret",
    )

    user = asyncio.run(create_user(payload=payload, session=session, admin=admin))

    assert user.password_hash != payload.password
    assert verify_password(payload.password, user.password_hash)
    audit = session.add.call_args_list[-1].args[0]
    assert "password" not in audit.after


def test_non_trainee_cannot_be_created_inside_trainee_group() -> None:
    admin = make_user(1, UserRole.ADMIN)
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = None
    payload = UserCreate(
        username="grouped-admin",
        full_name="Администратор группы",
        role=UserRole.ADMIN,
        password="training-secret",
        group_id=7,
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(create_user(payload=payload, session=session, admin=admin))

    assert error.value.status_code == 422
    session.add.assert_not_called()


def test_changing_trainee_role_removes_group_membership() -> None:
    admin = make_user(1, UserRole.ADMIN)
    trainee = make_user(3, UserRole.TRAINEE)
    trainee.group_id = 7
    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = trainee

    updated = asyncio.run(
        update_user(
            user_id=trainee.id,
            payload=UserUpdate(role=UserRole.INSTRUCTOR),
            session=session,
            admin=admin,
        )
    )

    assert updated.role == UserRole.INSTRUCTOR
    assert updated.group_id is None


def test_admin_can_create_named_trainee_group_with_audit() -> None:
    admin = make_user(1, UserRole.ADMIN)
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = None

    async def assign_group_id() -> None:
        group = next(
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], UserGroup)
        )
        group.id = 7

    session.flush.side_effect = assign_group_id
    result = asyncio.run(
        create_user_group(
            payload=UserGroupCreate(name="Группа ДДС-24", description="Вечерний поток"),
            session=session,
            admin=admin,
        )
    )

    assert result.id == 7
    assert result.name == "Группа ДДС-24"
    audit = session.add.call_args_list[-1].args[0]
    assert audit.action == "USER_GROUP_CREATED"


def test_admin_can_rename_trainee_group() -> None:
    admin = make_user(1, UserRole.ADMIN)
    group = UserGroup(id=7, name="Старая группа", description="")
    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = group
    session.scalar.side_effect = [None, 3]

    result = asyncio.run(
        update_user_group(
            group_id=group.id,
            payload=UserGroupUpdate(name="Новая группа", description="Утренний поток"),
            session=session,
            admin=admin,
        )
    )

    assert result.name == "Новая группа"
    assert result.description == "Утренний поток"
    assert result.member_count == 3
    audit = session.add.call_args.args[0]
    assert audit.action == "USER_GROUP_UPDATED"


def test_deleting_group_keeps_members_and_writes_audit() -> None:
    admin = make_user(1, UserRole.ADMIN)
    group = UserGroup(id=7, name="Группа ДДС-24", description="Вечерний поток")
    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = group

    asyncio.run(delete_user_group(group_id=group.id, session=session, admin=admin))

    session.execute.assert_awaited_once()
    session.delete.assert_awaited_once_with(group)
    audit = session.add.call_args.args[0]
    assert audit.action == "USER_GROUP_DELETED"
    assert audit.before["name"] == "Группа ДДС-24"
    session.commit.assert_awaited_once()


def test_admin_can_delete_another_user_with_audit() -> None:
    admin = make_user(1, UserRole.ADMIN)
    trainee = make_user(3, UserRole.TRAINEE)
    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = trainee

    asyncio.run(delete_user(user_id=trainee.id, session=session, admin=admin))

    session.delete.assert_awaited_once_with(trainee)
    audit = session.add.call_args.args[0]
    assert audit.action == "USER_DELETED"
    assert audit.before["username"] == trainee.username
    session.commit.assert_awaited_once()


def test_admin_cannot_delete_current_account() -> None:
    admin = make_user(1, UserRole.ADMIN)
    session = AsyncMock()
    session.get.return_value = admin

    with pytest.raises(HTTPException) as error:
        asyncio.run(delete_user(user_id=admin.id, session=session, admin=admin))

    assert error.value.status_code == 409
    session.delete.assert_not_awaited()


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
