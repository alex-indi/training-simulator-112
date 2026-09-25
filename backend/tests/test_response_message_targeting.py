"""Planned group messages wait for and reach the selected dispatch service."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_scenario_library import AsyncAdapter

from app.db.base import Base
from app.modules.admin.models import UserGroup  # noqa: F401
from app.modules.identity.models import User, UserRole
from app.modules.incident_classifier.models import DispatchService
from app.modules.incidents.models import Incident
from app.modules.response.models import ResponseAssignment, ResponseMessage, ResponseUnit
from app.modules.scenario_library.instance_models import (
    ScenarioInstance,
    ScenarioInstanceEvent,
    ScenarioRuntimeEvent,
)
from app.modules.scenario_library.models import ScenarioTemplate
from app.modules.scenario_library.runtime import release_due_events
from app.modules.training.models import TrainingRun, TrainingSession, TrainingSessionState


def test_response_message_waits_for_target_and_is_delivered_once():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        instructor = User(username="teacher", full_name="Teacher", role=UserRole.INSTRUCTOR)
        trainee = User(username="student", full_name="Student", role=UserRole.TRAINEE)
        service_101 = DispatchService(official_name="101", source_reference="CAT:101")
        service_103 = DispatchService(official_name="103", source_reference="CAT:103")
        db.add_all([instructor, trainee, service_101, service_103])
        db.flush()
        template = ScenarioTemplate(
            name="Пожар", created_by_user_id=instructor.id, initial_title="Дым"
        )
        session = TrainingSession(
            title="Занятие", instructor_id=instructor.id, state=TrainingSessionState.ACTIVE
        )
        run = TrainingRun(trainee_id=trainee.id, dds_profile="ДДС", workstation_number=1)
        session.runs.append(run)
        db.add_all([template, session])
        db.flush()
        instance = ScenarioInstance(
            scenario_template_id=template.id,
            created_by_user_id=instructor.id,
            name="Пожар",
            difficulty=2,
            generation_seed=1,
            classifier_snapshot={},
            object_snapshot={},
            service_snapshot=[
                {"service_id": service_101.id, "official_name": "101"},
                {"service_id": service_103.id, "official_name": "103"},
            ],
            initial_state_snapshot={},
            expected_actions_snapshot=[],
            assessment_criteria_snapshot=[],
            template_snapshot={},
        )
        db.add(instance)
        db.flush()
        planned = ScenarioInstanceEvent(
            scenario_instance_id=instance.id,
            sequence_number=1,
            offset_seconds=10,
            event_type="RESPONSE_MESSAGE",
            title="Доклад 103",
            description="Обнаружен пострадавший",
            source_type="RESPONSE_UNIT",
            payload_snapshot={
                "description": "Обнаружен пострадавший",
                "target_service_id": service_103.id,
                "target_service_name": "103",
                "target_service_source": "CAT:103",
            },
        )
        db.add(planned)
        db.flush()
        start = datetime.now(UTC)
        incident = Incident(
            training_session_id=session.id,
            scenario_instance_id=instance.id,
            training_run_id=run.id,
            incident_number="СЦ-1",
            reported_at=start,
            delivered_at=start,
            source="SCENARIO_INSTANCE",
            address="Адрес",
            description="Дым",
            incident_type="Пожар",
            source_snapshot={},
        )
        db.add(incident)
        db.flush()
        event = ScenarioRuntimeEvent(
            incident_id=incident.id,
            scenario_instance_event_id=planned.id,
            event_type="RESPONSE_MESSAGE",
            offset_seconds=10,
            payload_snapshot=dict(planned.payload_snapshot),
        )
        db.add(event)
        db.flush()
        tick_time = start + timedelta(seconds=11)

        async def tick():
            return await release_due_events(AsyncAdapter(db), session, tick_time)

        assert asyncio.run(tick()) == ([], [])
        assert event.status == "PENDING"

        unit_101 = ResponseUnit(name="Группа 101", dds_profile="ДДС")
        unit_103 = ResponseUnit(name="Группа 103", dds_profile="ДДС")
        db.add_all([unit_101, unit_103])
        db.flush()
        assignment_101 = ResponseAssignment(
            incident_id=incident.id, response_unit_id=unit_101.id, training_run_id=run.id
        )
        assignment_101.dispatch_service_id = service_101.id
        db.add(assignment_101)
        db.flush()
        assert asyncio.run(tick()) == ([], [])
        assert event.status == "PENDING"

        assignment_103 = ResponseAssignment(
            incident_id=incident.id, response_unit_id=unit_103.id, training_run_id=run.id
        )
        assignment_103.dispatch_service_id = service_103.id
        db.add(assignment_103)
        db.flush()
        released, notifications = asyncio.run(tick())
        db.flush()
        assert released == [incident.id]
        assert len(notifications) == 1
        assert notifications[0][0].response_assignment_id == assignment_103.id
        assert notifications[0][1] == trainee.id
        assert event.status == "RELEASED"
        assert asyncio.run(tick()) == ([], [])
        messages = db.scalars(select(ResponseMessage)).all()
        assert len(messages) == 1
        assert messages[0].response_assignment_id == assignment_103.id
    engine.dispose()
