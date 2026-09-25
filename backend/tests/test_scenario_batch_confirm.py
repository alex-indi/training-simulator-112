"""A reviewed set enters the shared queue in one transaction."""

import asyncio

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_scenario_library import AsyncAdapter

from app.db.base import Base
from app.db.dependencies import get_database_session
from app.modules.admin import models as admin_models  # noqa: F401
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incident_classifier.models import IncidentClassifierRule
from app.modules.incidents import models as incident_models  # noqa: F401
from app.modules.response import models as response_models  # noqa: F401
from app.modules.scenario_library.instance_models import ScenarioInstance, ScenarioInstanceEvent
from app.modules.scenario_library.instances import session_router
from app.modules.scenario_library.models import ScenarioTemplate
from app.modules.training.models import (
    QueueMode,
    ScenarioQueueItem,
    TrainingGroup,
    TrainingRun,
    TrainingSession,
)


def test_confirm_batch_is_atomic_and_targets_shared_queue():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        instructor = User(username="instructor", full_name="Teacher", role=UserRole.INSTRUCTOR)
        trainee_a = User(username="trainee-a", full_name="A", role=UserRole.TRAINEE)
        trainee_b = User(username="trainee-b", full_name="B", role=UserRole.TRAINEE)
        rule = IncidentClassifierRule(
            incident_group="Пожар", final_incident_type="Пожар в школе", source_reference="test:1"
        )
        db.add_all([instructor, trainee_a, trainee_b, rule])
        db.flush()
        template = ScenarioTemplate(
            name="Пожар в школе", status="READY", difficulty=3,
            classifier_rule_id=rule.id, created_by_user_id=instructor.id,
            initial_title="Дым", initial_description="На этаже дым",
        )
        training = TrainingSession(title="Занятие", instructor_id=instructor.id)
        group = TrainingGroup(name="Первая группа", queue_mode=QueueMode.SHARED_QUEUE)
        training.groups.append(group)
        training.runs.extend([
            TrainingRun(trainee_id=trainee_a.id, group=group, queue_mode=QueueMode.SHARED_QUEUE),
            TrainingRun(trainee_id=trainee_b.id, group=group, queue_mode=QueueMode.SHARED_QUEUE),
        ])
        db.add_all([template, training])
        db.flush()

        def draft(index):
            return ScenarioInstance(
                scenario_template_id=template.id,
                training_session_id=training.id,
                created_by_user_id=instructor.id,
                name=f"Школа №{index}", difficulty=3, generation_seed=index,
                status="DRAFT", classifier_snapshot={"final_incident_type": "Пожар"},
                object_snapshot={"name": f"Школа №{index}", "address": f"Адрес {index}"},
                service_snapshot=[],
                initial_state_snapshot={
                    "title": "Дым", "description": f"Дым в школе №{index}",
                    "render": {"rendered_text": f"дым в школе №{index}"},
                },
                expected_actions_snapshot=[], assessment_criteria_snapshot=[],
                template_snapshot={"id": template.id, "version": 1},
                events=[ScenarioInstanceEvent(
                    sequence_number=1, offset_seconds=60, event_type="RESPONSE_MESSAGE",
                    title="Прибытие", description="На месте", source_type="RESPONSE_UNIT",
                    payload_snapshot={"render": {"rendered_text": "на месте"}},
                )],
            )

        first, second = draft(1), draft(2)
        db.add_all([first, second])
        db.commit()
        app = FastAPI()
        app.include_router(session_router)
        principal = {"user": instructor}

        async def db_override():
            yield AsyncAdapter(db)

        app.dependency_overrides[get_database_session] = db_override
        app.dependency_overrides[get_current_user] = lambda: principal["user"]

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                path = f"/api/training/sessions/{training.id}/scenario-instances/confirm-batch"
                payload = {
                    "instance_ids": [first.id, second.id], "training_group_id": group.id
                }
                second.initial_state_snapshot = {"title": "Дым", "description": "Без текста"}
                db.commit()
                invalid = await client.post(path, json=payload)
                assert invalid.status_code == 409, invalid.text
                assert first.status == second.status == "DRAFT"
                assert db.scalars(select(ScenarioQueueItem)).all() == []

                second.initial_state_snapshot = {
                    "title": "Дым", "description": "Дым во второй школе",
                    "render": {"rendered_text": "дым во второй школе"},
                }
                db.commit()
                result = await client.post(path, json=payload)
                assert result.status_code == 200, result.text
                assert result.json()["count"] == 2
                assert first.status == second.status == "CONFIRMED"
                queued = db.scalars(
                    select(ScenarioQueueItem).order_by(ScenarioQueueItem.position)
                ).all()
                assert [item.scenario_instance_id for item in queued] == [first.id, second.id]
                assert all(item.training_group_id == group.id and item.approved for item in queued)
                assert [item.snapshot["description"] for item in queued] == [
                    "дым в школе №1", "дым во второй школе"
                ]
                assert (await client.post(path, json=payload)).status_code == 409
                assert len(db.scalars(select(ScenarioQueueItem)).all()) == 2
                principal["user"] = trainee_a
                assert (await client.post(path, json=payload)).status_code == 403

        asyncio.run(run())
    engine.dispose()
