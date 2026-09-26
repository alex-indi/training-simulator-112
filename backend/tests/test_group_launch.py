"""Prepared group packs become independent runtime queues only at launch."""

import asyncio
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_scenario_library import AsyncAdapter

from app.db.base import Base
from app.db.dependencies import get_database_session
from app.modules.admin import models as admin_models  # noqa: F401
from app.modules.admin.models import UserGroup
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incident_classifier.models import IncidentClassifierRule
from app.modules.incidents import models as incident_models  # noqa: F401
from app.modules.incidents.models import DDSResponseStatus, Incident
from app.modules.response import models as response_models  # noqa: F401
from app.modules.scenario_library.instance_models import ScenarioInstance
from app.modules.scenario_library.models import ScenarioTemplate
from app.modules.training.delivery import tick_session
from app.modules.training.models import (
    QueueMode,
    ScenarioQueueItem,
    TrainingGroup,
    TrainingRun,
    TrainingSession,
)
from app.modules.training.router import router


def test_four_trainees_auto_assign_and_launch_shared_and_individual_pools():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        teacher = User(username="teacher", full_name="Teacher", role=UserRole.INSTRUCTOR)
        sources = [UserGroup(name="A", code="A", created_by_user_id=None),
                   UserGroup(name="B", code="B", created_by_user_id=None)]
        db.add_all([teacher, *sources])
        db.flush()
        students = [
            User(username=f"student{index}", full_name=f"Student {index}",
                 role=UserRole.TRAINEE, group_id=sources[index // 2].id)
            for index in range(4)
        ]
        rule = IncidentClassifierRule(
            incident_group="Пожар", final_incident_type="Пожар", source_reference="test:1"
        )
        db.add_all([*students, rule])
        db.flush()
        template = ScenarioTemplate(
            name="Пожар", status="READY", difficulty=3,
            classifier_rule_id=rule.id, created_by_user_id=teacher.id,
            initial_title="Дым", initial_description="Дым",
        )
        session = TrainingSession(title="Занятие", instructor_id=teacher.id,
                                  mode="FIXED_SET", workstation_count=4)
        groups = [
            TrainingGroup(name="A", source_user_group_id=sources[0].id,
                          queue_mode=QueueMode.SHARED_QUEUE),
            TrainingGroup(name="B", source_user_group_id=sources[1].id,
                          queue_mode=QueueMode.INDIVIDUAL_QUEUE),
        ]
        session.groups.extend(groups)
        db.add_all([template, session])
        db.flush()
        for group, count in zip(groups, (8, 6)):
            for index in range(count):
                db.add(ScenarioInstance(
                    scenario_template_id=template.id, training_session_id=session.id,
                    training_group_id=group.id, created_by_user_id=teacher.id,
                    name=f"{group.name}-{index}", difficulty=3, generation_seed=index,
                    status="CONFIRMED", classifier_snapshot={"final_incident_type": "Пожар"},
                    object_snapshot={"name": "Школа", "address": "Адрес"},
                    service_snapshot=[], initial_state_snapshot={
                        "description": "Исходная ситуация",
                        "render": {"rendered_text": "Готовый текст"},
                    }, expected_actions_snapshot=[], assessment_criteria_snapshot=[],
                    template_snapshot={"name": "Пожар"}, events=[],
                ))
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
                for index, student in enumerate(students):
                    current[0] = student
                    response = await client.post(
                        f"{path}/join", json={"workstation_number": index + 1}
                    )
                    assert response.status_code == 200, response.text
                current[0] = teacher
                read = (await client.get(path)).json()
                assert [run["group_id"] for run in read["runs"]] == [
                    groups[0].id, groups[0].id, groups[1].id, groups[1].id
                ]
                moved = await client.post(
                    f"{path}/assign", json={"run_ids": [read["runs"][0]["id"]],
                                            "group_id": groups[1].id}
                )
                assert moved.status_code == 200, moved.text
                assert db.get(User, students[0].id).group_id == sources[0].id
                original = read["runs"][0]
                moved_run = next(run for run in moved.json()["runs"] if run["id"] == original["id"])
                assert {
                    key: moved_run[key] for key in ("dds_profile", "difficulty", "queue_mode")
                } == {
                    key: original[key] for key in ("dds_profile", "difficulty", "queue_mode")
                }
                assert (
                    db.get(TrainingRun, read["runs"][0]["id"]).queue_mode
                    == QueueMode.SHARED_QUEUE
                )
                restored = await client.post(
                    f"{path}/assign", json={"run_ids": [read["runs"][0]["id"]],
                                            "group_id": groups[0].id}
                )
                assert restored.status_code == 200, restored.text
                assert restored.json()["readiness"]["can_start"]
                assert (await client.post(f"{path}/prepare")).status_code == 200
                launched = await client.post(f"{path}/start")
                assert launched.status_code == 200, launched.text
                assert launched.json()["state"] == "ACTIVE"
                items = db.scalars(select(ScenarioQueueItem).order_by(ScenarioQueueItem.id)).all()
                shared = [item for item in items if item.training_group_id == groups[0].id]
                assert len(shared) == 8
                personal = [item for item in items if item.training_run_id is not None]
                assert len(personal) == 12
                each = [[item for item in personal if item.training_run_id == run["id"]]
                        for run in read["runs"][2:]]
                assert [len(pool) for pool in each] == [6, 6]
                assert {item.scenario_instance_id for item in each[0]}.isdisjoint(
                    {item.scenario_instance_id for item in each[1]}
                )
                assert [item.snapshot["description"] for item in each[0]] == [
                    item.snapshot["description"] for item in each[1]
                ] == ["Готовый текст"] * 6
                delivered_ids = await tick_session(AsyncAdapter(db), session.id, datetime.now(UTC))
                assert len(delivered_ids) == 20
                incidents = db.scalars(select(Incident).order_by(Incident.id)).all()
                first = next(
                    item for item in incidents
                    if item.training_run_id == read["runs"][2]["id"]
                )
                second = next(
                    item for item in incidents
                    if item.training_run_id == read["runs"][3]["id"]
                )
                assert first.id != second.id
                first.dds_status = DDSResponseStatus.COMPLETED
                db.flush()
                assert second.dds_status != DDSResponseStatus.COMPLETED

        asyncio.run(run())
    engine.dispose()
