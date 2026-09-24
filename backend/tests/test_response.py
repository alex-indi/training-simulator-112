"""Проверки назначения виртуальной группы и независимого хода реагирования."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import DDSResponseStatus, Incident
from app.modules.incidents.workflow import create_delivered_incident
from app.modules.response.models import (
    ResponseAssignment,
    ResponseAssignmentState,
    ResponseMessage,
    ResponseMessageSender,
    ResponseUnit,
)
from app.modules.response.realtime import notify_message_created, sio
from app.modules.response.router import apply_response_scenario_event, assign_response_unit
from app.modules.response.schemas import (
    ResponseAssignmentCreate,
    ResponseScenarioEventCreate,
    ResponseScenarioMessageCreate,
    ResponseUnitCreate,
)
from app.modules.response.workflow import (
    STATE_REPORTS,
    InvalidResponseTransitionError,
    apply_scenario_event,
    create_assignment,
    create_message,
)
from app.modules.training.models import TrainingRun, TrainingSession, TrainingSessionState
from tests.test_incidents import make_snapshot


def test_one_unit_can_serve_multiple_incidents_without_changing_dds_status() -> None:
    """История реагирования переживает reload, а статус ДДС меняет только UT112-9."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)

    with Session(engine) as database:
        instructor = User(
            username="instructor", full_name="Преподаватель", role=UserRole.INSTRUCTOR
        )
        trainee = User(username="trainee", full_name="Диспетчер", role=UserRole.TRAINEE)
        training_session = TrainingSession(
            title="Учебная смена",
            instructor=instructor,
            trainees=[trainee],
            state=TrainingSessionState.ACTIVE,
            started_at=now,
        )
        run = TrainingRun(training_session=training_session, trainee=trainee, dds_profile="ДДС")
        unit = ResponseUnit(name="Группа 1", dds_profile="ДДС", description="", is_active=True)
        database.add_all([training_session, run, unit])
        database.flush()

        incidents = []
        for number in ("112-2026-0007", "112-2026-0008"):
            snapshot = make_snapshot().model_dump(mode="json")
            snapshot["incident_number"] = number
            incident = create_delivered_incident(
                training_session_id=training_session.id,
                source_snapshot=snapshot,
                server_time=now,
            )
            incident.training_run = run
            incident.dds_status = DDSResponseStatus.ACCEPTED
            database.add(incident)
            incidents.append(incident)
        database.flush()

        assignments = [
            create_assignment(
                incident_id=incident.id,
                training_run_id=run.id,
                response_unit=unit,
                actor_user_id=trainee.id,
                server_time=now,
            )
            for incident in incidents
        ]
        database.add_all(assignments)
        apply_scenario_event(
            assignments[0],
            target_state=ResponseAssignmentState.ACKNOWLEDGED,
            event_key="step-1",
            server_time=now + timedelta(seconds=20),
        )
        database.commit()

        database.expire_all()
        restored = database.scalars(
            select(ResponseAssignment).order_by(ResponseAssignment.id)
        ).all()
        assert len(restored) == 2
        assert restored[0].response_unit_id == restored[1].response_unit_id
        assert restored[0].state == ResponseAssignmentState.ACKNOWLEDGED
        assert restored[1].state == ResponseAssignmentState.ASSIGNED
        assert [event.to_state for event in restored[0].events] == [
            ResponseAssignmentState.ASSIGNED,
            ResponseAssignmentState.ACKNOWLEDGED,
        ]
        assert all(
            database.get(Incident, item.incident_id).dds_status == DDSResponseStatus.ACCEPTED
            for item in restored
        )
    engine.dispose()


def test_scenario_transition_is_ordered_idempotent_and_server_timed() -> None:
    now = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
    unit = ResponseUnit(id=1, name="Группа", dds_profile="ДДС", is_active=True)
    assignment = create_assignment(
        incident_id=7,
        training_run_id=3,
        response_unit=unit,
        actor_user_id=4,
        server_time=now,
    )
    with pytest.raises(InvalidResponseTransitionError):
        apply_scenario_event(
            assignment,
            target_state=ResponseAssignmentState.ARRIVED,
            event_key="arrival",
            server_time=now,
        )

    changed_at = now + timedelta(seconds=20)
    first = apply_scenario_event(
        assignment,
        target_state=ResponseAssignmentState.ACKNOWLEDGED,
        event_key="acknowledged",
        server_time=changed_at,
    )
    repeated = apply_scenario_event(
        assignment,
        target_state=ResponseAssignmentState.ACKNOWLEDGED,
        event_key="acknowledged",
        server_time=changed_at + timedelta(minutes=1),
    )
    assert repeated is first
    assert assignment.state_changed_at == changed_at
    assert len(assignment.events) == 2


def test_messages_persist_per_assignment_without_changing_dds_status() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)

    with Session(engine) as database:
        instructor = User(
            username="instructor", full_name="Преподаватель", role=UserRole.INSTRUCTOR
        )
        trainee = User(username="trainee", full_name="Диспетчер", role=UserRole.TRAINEE)
        training_session = TrainingSession(
            title="Учебная смена",
            instructor=instructor,
            trainees=[trainee],
            state=TrainingSessionState.ACTIVE,
            started_at=now,
        )
        run = TrainingRun(training_session=training_session, trainee=trainee, dds_profile="ДДС")
        unit = ResponseUnit(name="Группа 1", dds_profile="ДДС", is_active=True)
        database.add_all([training_session, run, unit])
        database.flush()
        incident = create_delivered_incident(
            training_session_id=training_session.id,
            source_snapshot=make_snapshot().model_dump(mode="json"),
            server_time=now,
        )
        incident.training_run = run
        incident.dds_status = DDSResponseStatus.ACCEPTED
        database.add(incident)
        database.flush()
        assignment = create_assignment(
            incident_id=incident.id,
            training_run_id=run.id,
            response_unit=unit,
            actor_user_id=trainee.id,
            server_time=now,
        )
        database.add(assignment)
        database.flush()
        create_message(
            assignment,
            sender_type=ResponseMessageSender.DISPATCHER,
            body="Где вы?",
            actor_user_id=trainee.id,
            server_time=now,
        )
        report = create_message(
            assignment,
            sender_type=ResponseMessageSender.RESPONSE_UNIT,
            body="Подъезд перекрыт",
            event_key="obstacle",
            server_time=now + timedelta(seconds=5),
        )
        assert (
            create_message(
                assignment,
                sender_type=ResponseMessageSender.RESPONSE_UNIT,
                body="Подъезд перекрыт",
                event_key="obstacle",
            )
            is report
        )
        database.commit()
        database.expire_all()
        restored = database.scalars(select(ResponseMessage).order_by(ResponseMessage.id)).all()
        assert [message.sender_type for message in restored] == [
            ResponseMessageSender.DISPATCHER,
            ResponseMessageSender.RESPONSE_UNIT,
        ]
        assert restored[1].created_at.replace(tzinfo=UTC) == now + timedelta(seconds=5)
        assert database.get(Incident, incident.id).dds_status == DDSResponseStatus.ACCEPTED
        assert (
            database.get(ResponseAssignment, assignment.id).state
            == ResponseAssignmentState.ASSIGNED
        )
        assert STATE_REPORTS[ResponseAssignmentState.ASSIGNED]
    engine.dispose()


def test_scenario_message_key_reserves_state_reports() -> None:
    with pytest.raises(ValueError):
        ResponseScenarioMessageCreate(body="Доклад", event_key="state:departure")
    assert ResponseScenarioMessageCreate(
        body="  Подъезд перекрыт  ", event_key="  obstacle  "
    ).model_dump() == {"body": "Подъезд перекрыт", "event_key": "obstacle"}


def test_realtime_notification_contains_only_message_identity(monkeypatch) -> None:
    emit = AsyncMock()
    monkeypatch.setattr(sio, "emit", emit)
    asyncio.run(
        notify_message_created(
            SimpleNamespace(id=14, response_assignment_id=7),
            trainee_id=3,
        )
    )
    emit.assert_awaited_once_with(
        "response.message_created", {"assignment_id": 7, "message_id": 14}, room="user:3"
    )


def test_assignment_rejects_other_trainee_and_unaccepted_incident(monkeypatch) -> None:
    owner = User(id=3, username="owner", full_name="Диспетчер", role=UserRole.TRAINEE)
    other = User(id=4, username="other", full_name="Другой", role=UserRole.TRAINEE)
    session = TrainingSession(
        id=12,
        title="Смена",
        instructor_id=2,
        state=TrainingSessionState.ACTIVE,
        trainees=[owner, other],
    )
    run = TrainingRun(id=8, training_session_id=12, trainee_id=owner.id, dds_profile="ДДС")
    incident = create_delivered_incident(
        training_session_id=12,
        source_snapshot=make_snapshot().model_dump(mode="json"),
    )
    incident.id = 7
    incident.training_session = session
    incident.training_run = run
    incident.training_run_id = run.id
    monkeypatch.setattr(
        "app.modules.response.router._load_incident", AsyncMock(return_value=incident)
    )
    database = MagicMock()

    with pytest.raises(HTTPException) as foreign_error:
        asyncio.run(
            assign_response_unit(7, ResponseAssignmentCreate(response_unit_id=1), other, database)
        )
    assert foreign_error.value.status_code == 404

    with pytest.raises(HTTPException) as unaccepted_error:
        asyncio.run(
            assign_response_unit(7, ResponseAssignmentCreate(response_unit_id=1), owner, database)
        )
    assert unaccepted_error.value.status_code == 409
    database.add.assert_not_called()


@pytest.mark.parametrize("field", ["name", "dds_profile"])
def test_response_unit_required_text_rejects_whitespace(field) -> None:
    payload = {"name": "Группа", "dds_profile": "ДДС"}
    payload[field] = "   "
    with pytest.raises(ValueError):
        ResponseUnitCreate(**payload)


def test_assignment_notifies_session_and_duplicate_constraint_is_conflict(monkeypatch) -> None:
    owner = User(id=3, username="owner", role=UserRole.TRAINEE)
    session = TrainingSession(
        id=12, instructor_id=2, state=TrainingSessionState.ACTIVE, trainees=[owner]
    )
    run = TrainingRun(id=8, trainee_id=owner.id, dds_profile="ДДС")
    incident = create_delivered_incident(
        training_session_id=12, source_snapshot=make_snapshot().model_dump(mode="json"),
    )
    incident.id = 7
    incident.training_session = session
    incident.training_run = run
    incident.dds_status = DDSResponseStatus.ACCEPTED
    incident.training_run_id = run.id
    unit = ResponseUnit(
        id=5, name="Группа", dds_profile="ДДС", description="", is_active=True
    )
    result = MagicMock()
    result.one_or_none.return_value = unit
    database = MagicMock()
    database.scalars = AsyncMock(return_value=result)
    database.scalar = AsyncMock(return_value=None)
    database.commit = AsyncMock()
    database.rollback = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(
        "app.modules.response.router._load_incident", AsyncMock(return_value=incident)
    )
    monkeypatch.setattr("app.modules.response.router.publish_session_event", publish)

    def assign_ids(assignment) -> None:
        assignment.id = 9
        assignment.events[0].id = 10

    database.add.side_effect = assign_ids
    response = asyncio.run(assign_response_unit(
        7, ResponseAssignmentCreate(response_unit_id=5), owner, database,
    ))
    assert response.id == 9
    publish.assert_awaited_once_with("response.assignment_created", 12, 7)

    database.commit = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("duplicate")))
    with pytest.raises(HTTPException) as error:
        asyncio.run(assign_response_unit(
            7, ResponseAssignmentCreate(response_unit_id=5), owner, database,
        ))
    assert error.value.status_code == 409
    database.rollback.assert_awaited_once()


def test_response_state_transition_notifies_session(monkeypatch) -> None:
    instructor = User(id=2, username="instructor", role=UserRole.INSTRUCTOR)
    session = TrainingSession(id=12, instructor_id=2, state=TrainingSessionState.ACTIVE)
    incident = create_delivered_incident(
        training_session_id=12, source_snapshot=make_snapshot().model_dump(mode="json"),
    )
    incident.id = 7
    incident.training_session = session
    unit = ResponseUnit(
        id=5, name="Группа", dds_profile="ДДС", description="", is_active=True
    )
    assignment = create_assignment(
        incident_id=7, training_run_id=8, response_unit=unit, actor_user_id=3,
    )
    assignment.id = 9
    assignment.incident = incident
    assignment.events[0].id = 10
    result = MagicMock()
    result.one_or_none.return_value = assignment
    database = MagicMock()
    database.scalars = AsyncMock(return_value=result)
    database.commit = AsyncMock(side_effect=lambda: setattr(assignment.events[-1], "id", 11))
    publish = AsyncMock()
    monkeypatch.setattr("app.modules.response.router.publish_session_event", publish)

    response = asyncio.run(apply_response_scenario_event(
        9,
        ResponseScenarioEventCreate(
            event_key="acknowledged", target_state=ResponseAssignmentState.ACKNOWLEDGED,
        ),
        instructor, database,
    ))
    assert response.state == ResponseAssignmentState.ACKNOWLEDGED
    publish.assert_awaited_once_with("response.state_changed", 12, 7)
