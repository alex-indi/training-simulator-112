"""Права архивирования READY-сценариев."""

from app.modules.identity.models import User, UserRole
from app.modules.scenario_library.models import ScenarioTemplate
from app.modules.scenario_library.router import can_archive


def user(user_id: int, role: UserRole) -> User:
    return User(
        id=user_id,
        username=f"user-{user_id}",
        full_name=f"User {user_id}",
        role=role,
    )


def test_author_can_archive_own_scenario():
    scenario = ScenarioTemplate(created_by_user_id=10)
    assert can_archive(scenario, user(10, UserRole.INSTRUCTOR)) is True


def test_other_instructor_cannot_archive_scenario():
    scenario = ScenarioTemplate(created_by_user_id=10)
    assert can_archive(scenario, user(11, UserRole.INSTRUCTOR)) is False


def test_admin_can_archive_any_scenario():
    scenario = ScenarioTemplate(created_by_user_id=10)
    assert can_archive(scenario, user(99, UserRole.ADMIN)) is True
