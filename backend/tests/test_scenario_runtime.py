"""A prepared instance reaches the ordinary queue, Incident and timed history."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_scenario_library import AsyncAdapter

from app.db.base import Base
from app.db.dependencies import get_database_session
from app.modules.admin.models import UserGroup  # noqa: F401
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import DDSResponseStatus, Incident, IncidentAction
from app.modules.scenario_library.instance_models import (
    ScenarioInstance,
    ScenarioInstanceEvent,
    ScenarioRuntimeEvent,
)
from app.modules.scenario_library.instances import instance_router
from app.modules.scenario_library.models import ScenarioTemplate
from app.modules.training.delivery import tick_session
from app.modules.training.models import (
    QueueMode,
    ScenarioEvent,
    ScenarioQueueItem,
    SessionPause,
    TrainingMode,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
)


def test_instance_queue_delivery_and_pause_hide_future_events():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        instructor = User(username="teacher", full_name="Teacher", role=UserRole.INSTRUCTOR)
        trainee = User(username="student", full_name="Student", role=UserRole.TRAINEE)
        db.add_all([instructor, trainee])
        db.flush()
        template = ScenarioTemplate(
            name="Исходный шаблон",
            status="READY",
            difficulty=2,
            classifier_rule_id=1,
            created_by_user_id=instructor.id,
            initial_title="Задымление",
            initial_description="Исходный текст",
        )
        training = TrainingSession(
            title="Занятие", instructor_id=instructor.id, mode=TrainingMode.FIXED_SET
        )
        training.trainees.append(trainee)
        run = TrainingRun(
            trainee_id=trainee.id,
            queue_mode=QueueMode.INDIVIDUAL_QUEUE,
            workstation_number=1,
            dds_profile="Пожарная охрана",
        )
        training.runs.append(run)
        db.add_all([template, training])
        db.flush()
        instance = ScenarioInstance(
            scenario_template_id=template.id,
            training_session_id=training.id,
            created_by_user_id=instructor.id,
            name="Пожар в школе",
            difficulty=2,
            generation_seed=1,
            status="CONFIRMED",
            classifier_snapshot={"final_incident_type": "Пожар", "features": []},
            object_snapshot={"name": "Школа", "address": "Исходный адрес"},
            service_snapshot=[{"official_name": "Пожарная охрана"}],
            initial_state_snapshot={"title": "Дым", "description": "Первый звонок"},
            expected_actions_snapshot=[{"action": "ACCEPT"}],
            assessment_criteria_snapshot=[{"name": "Время"}],
            template_snapshot={"name": "Исходный шаблон"},
            events=[
                ScenarioInstanceEvent(
                    sequence_number=0,
                    offset_seconds=0,
                    event_type="INITIAL_REPORT",
                    title="Звонок",
                    description="Первый звонок",
                    source_type="CALLER",
                    payload_snapshot={"description": "Первый звонок"},
                ),
                ScenarioInstanceEvent(
                    sequence_number=1,
                    offset_seconds=60,
                    event_type="ADDITIONAL_INFO",
                    title="Уточнение",
                    description="Есть пострадавший",
                    source_type="CALLER",
                    payload_snapshot={"description": "Есть пострадавший"},
                ),
            ],
        )
        db.add(instance)
        db.commit()
        app = FastAPI()
        app.include_router(instance_router)
        principal = {"user": instructor}

        async def db_override():
            yield AsyncAdapter(db)

        app.dependency_overrides[get_database_session] = db_override
        app.dependency_overrides[get_current_user] = lambda: principal["user"]

        async def run_flow():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                url = f"/api/scenario-instances/{instance.id}/materialize"
                first = await client.post(url, json={"training_run_id": run.id})
                assert first.status_code == 200, first.text
                again = await client.post(url, json={"training_run_id": run.id})
                assert again.json() == first.json()
                item = db.scalar(select(ScenarioQueueItem))
                assert item.snapshot["address"] == "Исходный адрес"
                assert "assessment" not in str(item.snapshot)
                assert "Есть пострадавший" not in str(item.snapshot)
                item.approved = True
                training.state = TrainingSessionState.ACTIVE
                start = datetime.now(UTC)
                training.started_at = start
                db.commit()
                assert await tick_session(AsyncAdapter(db), training.id, start) == [
                    item.incident_id
                ]
                incident = db.get(Incident, item.incident_id)
                assert incident.scenario_instance_id == instance.id
                assert incident.dds_status == DDSResponseStatus.AWAITING_DECISION
                assert db.query(IncidentAction).filter_by(incident_id=incident.id).count() == 1
                event = db.scalar(select(ScenarioRuntimeEvent))
                assert event.status == "PENDING"
                assert db.query(ScenarioEvent).count() == 0
                training.paused_at = start + timedelta(seconds=30)
                db.add(
                    SessionPause(
                        training_session_id=training.id,
                        instructor_id=instructor.id,
                        started_at=training.paused_at,
                        finished_at=None,
                    )
                )
                db.commit()
                await tick_session(AsyncAdapter(db), training.id, start + timedelta(seconds=90))
                assert event.status == "PENDING"
                training.paused_at = None
                pause = db.scalar(select(SessionPause))
                pause.finished_at = start + timedelta(seconds=90)
                pause.duration_seconds = 60
                db.commit()
                db.expire(training, ["pauses"])
                await tick_session(AsyncAdapter(db), training.id, start + timedelta(seconds=91))
                assert event.status == "PENDING"
                await tick_session(AsyncAdapter(db), training.id, start + timedelta(seconds=121))
                assert event.status == "RELEASED"
                assert event.released_at is not None
                assert db.scalar(select(ScenarioEvent)).origin == "SCENARIO"
                assert incident.dds_status == DDSResponseStatus.AWAITING_DECISION
                principal["user"] = trainee
                assert (
                    await client.get(f"/api/scenario-instances/{instance.id}")
                ).status_code == 403
                assert (
                    await client.get(f"/api/scenario-instances/{instance.id}/materialization")
                ).status_code == 403

        asyncio.run(run_flow())
    engine.dispose()
