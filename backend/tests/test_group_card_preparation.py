"""A group can approve a mixed master set before any trainee connects."""

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
from app.modules.scenario_library.instance_models import ScenarioInstance
from app.modules.scenario_library.instances import session_router
from app.modules.scenario_library.models import ScenarioTemplate
from app.modules.training.models import (
    QueueMode,
    ScenarioQueueItem,
    TrainingGroup,
    TrainingRun,
    TrainingSession,
)


def test_group_master_set_can_mix_templates_and_approve_without_runs():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        instructor = User(username="instructor", full_name="Teacher", role=UserRole.INSTRUCTOR)
        rule = IncidentClassifierRule(
            incident_group="Пожар", final_incident_type="Пожар", source_reference="test:1"
        )
        db.add_all([instructor, rule])
        db.flush()
        fire = ScenarioTemplate(
            name="Пожар в школе",
            status="READY",
            difficulty=3,
            classifier_rule_id=rule.id,
            created_by_user_id=instructor.id,
            initial_title="Дым",
            initial_description="Дым",
        )
        road = ScenarioTemplate(
            name="ДТП",
            status="READY",
            difficulty=3,
            classifier_rule_id=rule.id,
            created_by_user_id=instructor.id,
            initial_title="ДТП",
            initial_description="ДТП",
        )
        training = TrainingSession(title="Занятие", instructor_id=instructor.id)
        first_group = TrainingGroup(name="Группа A", queue_mode=QueueMode.SHARED_QUEUE)
        second_group = TrainingGroup(name="Группа B", queue_mode=QueueMode.INDIVIDUAL_QUEUE)
        training.groups.extend([first_group, second_group])
        db.add_all([fire, road, training])
        db.flush()

        def card(template, group, index, text="подготовленный текст"):
            return ScenarioInstance(
                scenario_template_id=template.id,
                training_session_id=training.id,
                training_group_id=group.id,
                created_by_user_id=instructor.id,
                name=f"Карточка {index}",
                difficulty=3,
                generation_seed=index,
                status="DRAFT",
                classifier_snapshot={"final_incident_type": "Пожар"},
                object_snapshot={"name": f"Объект {index}", "address": "Адрес"},
                service_snapshot=[],
                initial_state_snapshot={"render": {"rendered_text": text}},
                expected_actions_snapshot=[],
                assessment_criteria_snapshot=[],
                template_snapshot={"name": template.name, "version": 1},
                events=[],
            )

        fire_card = card(fire, first_group, 1)
        road_card = card(road, first_group, 2, text="")
        other_card = card(road, second_group, 3)
        db.add_all([fire_card, road_card, other_card])
        db.commit()
        app = FastAPI()
        app.include_router(session_router)

        async def db_override():
            yield AsyncAdapter(db)

        app.dependency_overrides[get_database_session] = db_override
        app.dependency_overrides[get_current_user] = lambda: instructor

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                path = f"/api/training/sessions/{training.id}/groups/{first_group.id}/cards/approve"
                invalid = await client.post(path)
                assert invalid.status_code == 409, invalid.text
                assert fire_card.status == road_card.status == "DRAFT"
                road_card.initial_state_snapshot = {"render": {"rendered_text": "ДТП"}}
                db.commit()
                approved = await client.post(path)
                assert approved.status_code == 200, approved.text
                assert approved.json()["count"] == 2
                assert fire_card.status == road_card.status == "CONFIRMED"
                assert other_card.status == "DRAFT"
                extra = card(fire, first_group, 4)
                db.add(extra)
                db.commit()
                assert (await client.post(path)).json()["count"] == 3
                assert extra.status == "CONFIRMED"
                assert db.scalars(select(TrainingRun)).all() == []
                assert db.scalars(select(ScenarioQueueItem)).all() == []

        asyncio.run(run())
    engine.dispose()
