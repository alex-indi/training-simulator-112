"""Integration check against an isolated migrated PostgreSQL database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.dependencies import get_database_session
from app.modules.admin.models import UserGroup  # noqa: F401
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incident_classifier.models import DispatchService, IncidentClassifierRule
from app.modules.incidents.models import DDSResponseStatus, Incident, IncidentAction
from app.modules.response.models import ResponseAssignment, ResponseMessage, ResponseUnit
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


@pytest.mark.skipif(not os.getenv("UT112_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
def test_postgres_materialization_concurrency_delivery_and_event_clock():
    async def exercise():
        engine = create_async_engine(os.environ["UT112_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid4().hex[:12]
        user_id = 1_000_000_000 + int(unique[:7], 16)
        async with factory() as database:
            instructor = User(
                id=user_id,
                username=f"teacher_{unique}",
                full_name="Teacher",
                role=UserRole.INSTRUCTOR,
            )
            trainee = User(
                id=user_id + 1,
                username=f"student_{unique}",
                full_name="Student",
                role=UserRole.TRAINEE,
            )
            rule = IncidentClassifierRule(
                incident_group="Пожар",
                final_incident_type="Пожар в школе",
                source_reference=f"TEST:{unique}",
            )
            service = DispatchService(
                official_name="Пожарная охрана", source_reference=f"TEST:{unique}"
            )
            database.add_all([instructor, trainee, rule, service])
            await database.flush()
            template = ScenarioTemplate(
                name="Пожар в школе",
                status="READY",
                difficulty=2,
                classifier_rule_id=rule.id,
                created_by_user_id=instructor.id,
                initial_title="Дым",
                initial_description="Дым из окна",
            )
            training = TrainingSession(
                title="Занятие", instructor_id=instructor.id, mode=TrainingMode.FIXED_SET
            )
            training.trainees.append(trainee)
            training.runs.append(
                TrainingRun(
                    trainee_id=trainee.id,
                    queue_mode=QueueMode.INDIVIDUAL_QUEUE,
                    workstation_number=1,
                    dds_profile="Пожарная охрана",
                )
            )
            database.add_all([template, training])
            await database.flush()
            run_id = training.runs[0].id
            instance = ScenarioInstance(
                scenario_template_id=template.id,
                training_session_id=training.id,
                created_by_user_id=instructor.id,
                name="Пожар в школе №1",
                difficulty=2,
                generation_seed=1,
                status="CONFIRMED",
                classifier_snapshot={"final_incident_type": "Пожар в школе", "features": []},
                object_snapshot={"name": "Школа №1", "address": "Исходный адрес"},
                service_snapshot=[
                    {"service_id": service.id, "official_name": service.official_name}
                ],
                initial_state_snapshot={"title": "Дым", "description": "Первый звонок"},
                expected_actions_snapshot=[{"action": "ACCEPT"}],
                assessment_criteria_snapshot=[],
                template_snapshot={"name": "Пожар в школе"},
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
                    ScenarioInstanceEvent(
                        sequence_number=2,
                        offset_seconds=90,
                        event_type="RESPONSE_MESSAGE",
                        title="Группа",
                        description="Прибыли к месту",
                        source_type="RESPONSE_UNIT",
                        payload_snapshot={
                            "description": "Прибыли к месту",
                            "target_service_id": service.id,
                        },
                    ),
                ],
            )
            database.add(instance)
            await database.commit()
            session_id, instance_id = training.id, instance.id

        app = FastAPI()
        app.include_router(instance_router)

        async def database_override():
            async with factory() as database:
                yield database

        app.dependency_overrides[get_database_session] = database_override
        app.dependency_overrides[get_current_user] = lambda: instructor
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            url = f"/api/scenario-instances/{instance_id}/materialize"
            results = await asyncio.gather(
                *[client.post(url, json={"training_run_id": run_id}) for _ in range(2)]
            )
            assert all(result.status_code == 200 for result in results), [
                result.text for result in results
            ]
            assert results[0].json() == results[1].json()
            async with factory() as database:
                assert (
                    await database.scalar(
                        select(func.count(ScenarioQueueItem.id)).where(
                            ScenarioQueueItem.scenario_instance_id == instance_id
                        )
                    )
                    == 1
                )
                item = await database.scalar(
                    select(ScenarioQueueItem).where(
                        ScenarioQueueItem.scenario_instance_id == instance_id
                    )
                )
                assert "Есть пострадавший" not in str(item.snapshot)
                assert "expected_actions" not in str(item.snapshot)
                item.approved = True
                training = await database.get(TrainingSession, session_id)
                training.state = TrainingSessionState.ACTIVE
                start = datetime.now(UTC)
                training.started_at = start
                await database.commit()
            async with factory() as database:
                ids = await tick_session(database, session_id, start)
                assert len(ids) == 1
            async with factory() as database:
                assert await tick_session(database, session_id, start + timedelta(seconds=1)) == []
                incident = await database.get(Incident, ids[0])
                assert incident.scenario_instance_id == instance_id
                assert incident.dds_status == DDSResponseStatus.AWAITING_DECISION
                unit = ResponseUnit(
                    seed_code=f"runtime_{unique}",
                    name="Учебная группа",
                    dds_profile="Пожарная охрана",
                )
                database.add(unit)
                await database.flush()
                database.add(
                    ResponseAssignment(
                        incident_id=incident.id,
                        response_unit_id=unit.id,
                        training_run_id=run_id,
                        dispatch_service_id=service.id,
                    )
                )
                await database.commit()
                assert (
                    await database.scalar(
                        select(func.count(IncidentAction.id)).where(
                            IncidentAction.incident_id == ids[0]
                        )
                    )
                    == 1
                )
                event = await database.scalar(
                    select(ScenarioRuntimeEvent).where(
                        ScenarioRuntimeEvent.incident_id == ids[0],
                        ScenarioRuntimeEvent.event_type == "ADDITIONAL_INFO",
                    )
                )
                assert event.status == "PENDING"
                training = await database.get(TrainingSession, session_id)
                training.paused_at = start + timedelta(seconds=30)
                database.add(
                    SessionPause(
                        training_session_id=session_id,
                        instructor_id=instructor.id,
                        started_at=training.paused_at,
                    )
                )
                await database.commit()
            async with factory() as database:
                await tick_session(database, session_id, start + timedelta(seconds=90))
            async with factory() as database:
                training = await database.get(TrainingSession, session_id)
                training.paused_at = None
                pause = await database.scalar(
                    select(SessionPause).where(SessionPause.training_session_id == session_id)
                )
                pause.finished_at = start + timedelta(seconds=90)
                pause.duration_seconds = 60
                await database.commit()
            async with factory() as database:
                await tick_session(database, session_id, start + timedelta(seconds=91))
                event = await database.scalar(
                    select(ScenarioRuntimeEvent).where(
                        ScenarioRuntimeEvent.incident_id == ids[0],
                        ScenarioRuntimeEvent.event_type == "ADDITIONAL_INFO",
                    )
                )
                assert event.status == "PENDING"
            async with factory() as database:
                await tick_session(database, session_id, start + timedelta(seconds=121))
                event = await database.scalar(
                    select(ScenarioRuntimeEvent).where(
                        ScenarioRuntimeEvent.incident_id == ids[0],
                        ScenarioRuntimeEvent.event_type == "ADDITIONAL_INFO",
                    )
                )
                incident = await database.get(Incident, ids[0])
                assert event.status == "RELEASED" and event.released_at is not None
                assert incident.dds_status == DDSResponseStatus.AWAITING_DECISION
                assert (
                    await database.scalar(
                        select(func.count(ScenarioEvent.id)).where(
                            ScenarioEvent.scenario_instance_event_id
                            == event.scenario_instance_event_id
                        )
                    )
                    == 1
                )
            async with factory() as database:
                await tick_session(database, session_id, start + timedelta(seconds=151))
                message = await database.scalar(
                    select(ResponseMessage)
                    .join(ResponseAssignment)
                    .where(
                        ResponseAssignment.incident_id == ids[0],
                        ResponseMessage.event_key.like("scenario:%"),
                    )
                )
                assert message.body == "Прибыли к месту"
                assert (
                    await database.get(Incident, ids[0])
                ).dds_status == DDSResponseStatus.AWAITING_DECISION
        await engine.dispose()

    asyncio.run(exercise())
