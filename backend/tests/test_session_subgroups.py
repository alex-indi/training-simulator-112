"""Subgroup membership changes only the working structure of one session."""

import asyncio

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_scenario_library import AsyncAdapter

from app.db.base import Base
from app.db.dependencies import get_database_session
from app.modules.admin.models import UserGroup
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incident_classifier.models import IncidentClassifierRule
from app.modules.incidents import models as incident_models  # noqa: F401
from app.modules.response import models as response_models  # noqa: F401
from app.modules.scenario_library.instance_models import ScenarioInstance
from app.modules.scenario_library.models import ScenarioTemplate
from app.modules.training.models import QueueMode, ScenarioQueueItem, TrainingGroup, TrainingSession
from app.modules.training.router import router


def test_cross_source_subgroup_assignment_and_restoration():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        teacher = User(username="teacher45", full_name="Преподаватель", role=UserRole.INSTRUCTOR)
        sources = [
            UserGroup(name="ДДС-101-01", code="101", created_by_user_id=None),
            UserGroup(name="ДДС-102-01", code="102", created_by_user_id=None),
        ]
        db.add_all([teacher, *sources])
        db.flush()
        students = [
            User(
                username=f"student45_{index}",
                full_name=f"Обучаемый {index}",
                role=UserRole.TRAINEE,
                group_id=sources[0 if index < 4 else 1].id,
            )
            for index in range(7)
        ]
        session = TrainingSession(
            title="Занятие",
            instructor_id=teacher.id,
            mode="FIXED_SET",
            workstation_count=7,
        )
        session.groups.extend(
            [
                TrainingGroup(
                    name=source.name,
                    source_user_group_id=source.id,
                    difficulty="Средняя",
                    queue_mode=QueueMode.SHARED_QUEUE,
                )
                for source in sources
            ]
        )
        db.add_all([*students, session])
        db.commit()

        app = FastAPI()
        app.include_router(router)
        current = [teacher]
        app.dependency_overrides[get_current_user] = lambda: current[0]

        async def database():
            yield AsyncAdapter(db)

        app.dependency_overrides[get_database_session] = database

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                path = f"/api/training/sessions/{session.id}"
                initial = (await client.get(path)).json()
                assert [group["member_count"] for group in initial["groups"]] == [4, 3]
                chosen = [students[index].id for index in (0, 2, 5)]
                payload = {
                    "name": "Подгруппа А",
                    "member_user_ids": chosen,
                    "difficulty": "Высокая",
                    "queue_mode": "INDIVIDUAL_QUEUE",
                }
                created = await client.post(f"{path}/subgroups", json=payload)
                assert created.status_code == 200, created.text
                groups = created.json()["groups"]
                subgroup = next(group for group in groups if group["is_subgroup"])
                assert [group["member_count"] for group in groups] == [2, 2, 3]
                assert {member["id"] for member in subgroup["members"]} == set(chosen)
                conflict = await client.post(
                    f"{path}/subgroups",
                    json={
                        **payload,
                        "name": "Подгруппа Б",
                        "member_user_ids": [chosen[0]],
                    },
                )
                assert conflict.status_code == 409
                assert "другую подгруппу" in conflict.json()["detail"]
                source_delete = await client.delete(f"{path}/groups/{groups[0]['id']}")
                assert source_delete.status_code == 409

                for index in (0, 1, 5):
                    current[0] = students[index]
                    joined = await client.post(
                        f"{path}/join", json={"workstation_number": index + 1}
                    )
                    assert joined.status_code == 200, joined.text
                current[0] = teacher
                runs = (await client.get(path)).json()["runs"]
                assert (
                    next(run for run in runs if run["trainee_id"] == students[0].id)["group_id"]
                    == subgroup["id"]
                )
                assert (
                    next(run for run in runs if run["trainee_id"] == students[1].id)["group_id"]
                    == groups[0]["id"]
                )
                assert (
                    next(run for run in runs if run["trainee_id"] == students[5].id)["group_id"]
                    == subgroup["id"]
                )

                updated = await client.put(
                    f"{path}/subgroups/{subgroup['id']}",
                    json={
                        **payload,
                        "name": "Подгруппа повышенной сложности",
                        "member_user_ids": chosen[:2],
                    },
                )
                assert updated.status_code == 200, updated.text
                assert [group["member_count"] for group in updated.json()["groups"]] == [2, 3, 2]
                assert (
                    next(
                        run for run in updated.json()["runs"] if run["trainee_id"] == students[5].id
                    )["group_id"]
                    == groups[1]["id"]
                )

                all_in_subgroup = await client.put(
                    f"{path}/subgroups/{subgroup['id']}",
                    json={
                        **payload,
                        "member_user_ids": [student.id for student in students],
                    },
                )
                assert all_in_subgroup.status_code == 200, all_in_subgroup.text
                assert [group["member_count"] for group in all_in_subgroup.json()["groups"]] == [
                    0, 0, 7
                ]
                assert all_in_subgroup.json()["readiness"]["group_count"] == 1
                assert not any(
                    group["name"] in warning
                    for group in all_in_subgroup.json()["groups"][:2]
                    for warning in all_in_subgroup.json()["readiness"]["warnings"]
                )

                rule = IncidentClassifierRule(
                    incident_group="Пожар",
                    final_incident_type="Пожар",
                    source_reference="test:subgroup",
                )
                db.add(rule)
                db.flush()
                template = ScenarioTemplate(
                    name="Тест",
                    status="READY",
                    difficulty=3,
                    classifier_rule_id=rule.id,
                    created_by_user_id=teacher.id,
                    initial_title="Дым",
                    initial_description="Дым",
                )
                db.add(template)
                db.flush()
                card = ScenarioInstance(
                    scenario_template_id=template.id,
                    training_session_id=session.id,
                    training_group_id=subgroup["id"],
                    created_by_user_id=teacher.id,
                    name="Карточка подгруппы",
                    difficulty=3,
                    generation_seed=1,
                    status="DRAFT",
                    classifier_snapshot={},
                    object_snapshot={},
                    service_snapshot=[],
                    initial_state_snapshot={},
                    expected_actions_snapshot=[],
                    assessment_criteria_snapshot=[],
                    template_snapshot={},
                    events=[],
                )
                db.add(card)
                db.flush()
                queued = ScenarioQueueItem(
                    training_session_id=session.id,
                    training_group_id=subgroup["id"],
                    scenario_instance_id=card.id,
                    title="Карточка подгруппы",
                    snapshot={},
                    position=1,
                )
                db.add(queued)
                db.commit()

                removed = await client.delete(f"{path}/groups/{subgroup['id']}")
                assert removed.status_code == 200, removed.text
                assert db.get(ScenarioInstance, card.id) is None
                assert db.get(ScenarioQueueItem, queued.id) is None
                assert removed.json()["readiness"]["prepared_count"] == 0
                assert [group["member_count"] for group in removed.json()["groups"]] == [4, 3]
                restored_runs = removed.json()["runs"]
                assert (
                    next(run for run in restored_runs if run["trainee_id"] == students[0].id)[
                        "group_id"
                    ]
                    == groups[0]["id"]
                )
                assert (
                    next(run for run in restored_runs if run["trainee_id"] == students[5].id)[
                        "group_id"
                    ]
                    == groups[1]["id"]
                )
                assert db.get(User, students[0].id).group_id == sources[0].id
                assert db.get(User, students[5].id).group_id == sources[1].id
                session.state = "ACTIVE"
                db.commit()
                locked = await client.post(f"{path}/subgroups", json=payload)
                assert locked.status_code == 409

        asyncio.run(run())
    engine.dispose()
