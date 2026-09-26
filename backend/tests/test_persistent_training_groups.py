"""The instructor can prepare session groups before trainees connect."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.admin.models import UserGroup
from app.modules.identity.models import User, UserRole
from app.modules.response.models import (
    ResponseAssignment,  # noqa: F401 — registers relationship mapper
)
from app.modules.training.models import (
    QueueMode,
    TrainingMode,
    TrainingSession,
    TrainingSessionState,
)
from app.modules.training.router import create_group, update_group
from app.modules.training.schemas import GroupWrite
from app.modules.training.user_groups import UserGroupWrite, _check_owner, _members


def instructor(user_id: int = 2) -> User:
    return User(id=user_id, username=f"teacher{user_id}", role=UserRole.INSTRUCTOR)


def draft() -> TrainingSession:
    return TrainingSession(
        id=10, title="Практическое занятие", instructor_id=2,
        state=TrainingSessionState.DRAFT, mode=TrainingMode.FIXED_SET,
        groups=[], runs=[], trainees=[], queue_items=[],
        created_at=datetime(2026, 9, 26, tzinfo=UTC), workstation_count=30,
    )


def test_session_group_uses_owned_source_without_training_run() -> None:
    session = draft()
    source = UserGroup(
        id=7, name="ДДС пожарной охраны", code="ДДС-101-01",
        created_by_user_id=2, is_archived=False,
    )
    database = MagicMock()
    database.get = AsyncMock(return_value=source)

    async def save(_database, item):
        return item

    with patch("app.modules.training.router._load_session", new=AsyncMock(return_value=session)), \
         patch("app.modules.training.router._save", new=save):
        result = asyncio.run(create_group(
            10, GroupWrite(name="Подменённое имя", source_user_group_id=7,
                           difficulty="Средняя", queue_mode=QueueMode.SHARED_QUEUE),
            instructor(), database,
        ))

    assert result.runs == []
    assert result.groups[0].source_user_group_id == 7
    assert result.groups[0].name == source.name
    assert result.groups[0].difficulty == "Средняя"
    assert result.groups[0].queue_mode == QueueMode.SHARED_QUEUE


def test_instructor_cannot_attach_foreign_or_archived_source() -> None:
    for owner_id, archived in [(3, False), (2, True)]:
        session = draft()
        database = MagicMock()
        database.get = AsyncMock(return_value=UserGroup(
            id=7, name="Чужая группа", created_by_user_id=owner_id, is_archived=archived,
        ))
        with patch(
            "app.modules.training.router._load_session",
            new=AsyncMock(return_value=session),
        ):
            with pytest.raises(HTTPException) as error:
                asyncio.run(create_group(
                    10, GroupWrite(name="Группа", source_user_group_id=7), instructor(), database,
                ))
        assert error.value.status_code == 404
        assert session.groups == []


def test_group_source_cannot_be_changed_during_update() -> None:
    session = draft()
    from app.modules.training.models import TrainingGroup
    session.groups = [TrainingGroup(id=5, name="Группа", source_user_group_id=7)]
    with patch("app.modules.training.router._load_session", new=AsyncMock(return_value=session)):
        with pytest.raises(HTTPException) as error:
            asyncio.run(update_group(
                10, 5, GroupWrite(name="Группа", source_user_group_id=8), instructor(), MagicMock(),
            ))
    assert error.value.status_code == 409


def test_group_write_rejects_repeated_members() -> None:
    with pytest.raises(ValueError):
        UserGroupWrite(name="Группа", code="ДДС-101", member_ids=[3, 3])


def test_instructor_cannot_edit_foreign_group() -> None:
    with pytest.raises(HTTPException) as error:
        _check_owner(UserGroup(id=7, created_by_user_id=3), instructor())
    assert error.value.status_code == 404


def test_instructor_cannot_move_member_from_foreign_group() -> None:
    trainee = User(id=4, username="student", role=UserRole.TRAINEE, is_active=True, group_id=8)
    database = MagicMock()
    first = MagicMock()
    first.all.return_value = [trainee]
    database.scalars = AsyncMock(return_value=first)
    with pytest.raises(HTTPException) as error:
        asyncio.run(_members(database, [4]))
    assert error.value.status_code == 409
