"""Расчёт предварительного результата по фактической истории занятия."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.incidents.models import (
    DDSResponseStatus,
    Incident,
    IncidentAction,
    IncidentActionType,
    IncidentActivity,
    IncidentLifecycleState,
)
from app.modules.training.assessment import _score, assess_run
from app.modules.training.models import RunPause, SessionPause, TrainingRun


def test_assessment_uses_training_time_and_keeps_automatic_score_after_review():
    start = datetime(2026, 9, 24, 10, tzinfo=UTC)
    run = TrainingRun(id=7)
    action = IncidentAction(
        action=IncidentActionType.REJECT,
        is_system=False,
        status="REJECTED",
        comment="Объект вне зоны ответственности",
        created_at=start + timedelta(seconds=50),
    )
    incident = Incident(
        id=11,
        incident_number="КП-11",
        delivered_at=start,
        primary_status_at=start + timedelta(seconds=50),
        lifecycle_state=IncidentLifecycleState.FINISHED,
        dds_status=DDSResponseStatus.REJECTED,
        actions=[action],
        activities=[],
    )
    global_pause = SessionPause(
        started_at=start + timedelta(seconds=10), finished_at=start + timedelta(seconds=30)
    )
    run_pause = RunPause(
        started_at=start + timedelta(seconds=20), finished_at=start + timedelta(seconds=40)
    )

    result = assess_run(run, [incident], [global_pause], [run_pause])
    assert result.metrics["average_reaction_seconds"] == 20
    assert result.metrics["reaction_violations"] == 0
    assert result.deviations == []
    assert result.automatic_score == 100

    assert _score(result) == 100


def test_assessment_flags_unfinished_card_without_primary_decision():
    start = datetime(2026, 9, 24, 10, tzinfo=UTC)
    incident = Incident(
        id=12,
        incident_number="КП-12",
        delivered_at=start,
        lifecycle_state=IncidentLifecycleState.DELIVERED,
        dds_status=DDSResponseStatus.AWAITING_DECISION,
        actions=[],
        activities=[],
    )
    result = assess_run(TrainingRun(id=7), [incident], [], [])
    assert {item.kind for item in result.deviations} == {"NO_PRIMARY_STATUS"}
    assert result.metrics["critical_signals"] == 1
    assert result.automatic_score == 90


def test_assessment_matches_brigade_stages_to_later_dds_actions():
    start = datetime(2026, 9, 24, 16, 10, tzinfo=UTC)
    events = [
        ("EN_ROUTE", 60, "Выехали"),
        ("ARRIVED", 180, "Прибыли"),
        ("WORKING", 300, "Приступили к работам"),
        ("COMPLETED", 600, "Пожар ликвидирован"),
    ]
    actions = [
        (IncidentActionType.ACCEPT, 20),
        (IncidentActionType.START_RESPONSE, 78),
        (IncidentActionType.MARK_ARRIVAL, 240),
        (IncidentActionType.START_WORK, 315),
        (IncidentActionType.COMPLETE_WORK, 670),
    ]
    incident = Incident(
        id=13,
        incident_number="КП-13",
        delivered_at=start,
        primary_status_at=start + timedelta(seconds=20),
        finished_at=start + timedelta(seconds=670),
        lifecycle_state=IncidentLifecycleState.FINISHED,
        dds_status=DDSResponseStatus.COMPLETED,
        actions=[
            IncidentAction(
                action=action,
                status=action.value,
                is_system=False,
                created_at=start + timedelta(seconds=offset),
            )
            for action, offset in actions
        ],
        activities=[
            IncidentActivity(
                kind="TRAINING_BRIGADE",
                stage=stage,
                body=body,
                service_name="Бригада 101",
                event_key=f"brigade-101:{stage}",
                created_at=start + timedelta(seconds=offset),
            )
            for stage, offset, body in events
        ],
    )
    result = assess_run(TrainingRun(id=7), [incident], [], [])
    card = result.metrics["card_results"][0]
    assert card["primary"]["seconds"] == 20
    assert [step["seconds"] for step in card["brigade"]] == [18, 60, 15, 70]
    assert [step["severity"] for step in card["brigade"]] == ["OK", "MAJOR", "OK", "MAJOR"]
    assert result.metrics["major_errors"] == 2
    assert result.metrics["critical_signals"] == 0
    assert result.metrics["rules_version"] == 3


@pytest.mark.parametrize(
    ("reaction_seconds", "expected_severity", "expected_major_errors"),
    [
        (44, "OK", 0),
        (45, "OK", 0),
        (46, "MAJOR", 1),
    ],
)
def test_brigade_reaction_boundary_is_exactly_45_seconds(
    reaction_seconds: int,
    expected_severity: str,
    expected_major_errors: int,
):
    start = datetime(2026, 9, 24, 17, tzinfo=UTC)
    event_at = start + timedelta(seconds=60)
    incident = Incident(
        id=14,
        incident_number="КП-14",
        delivered_at=start,
        primary_status_at=start + timedelta(seconds=1),
        lifecycle_state=IncidentLifecycleState.OPENED,
        dds_status=DDSResponseStatus.ARRIVED,
        actions=[
            IncidentAction(
                action=IncidentActionType.ACCEPT,
                status=IncidentActionType.ACCEPT.value,
                is_system=False,
                created_at=start + timedelta(seconds=1),
            ),
            IncidentAction(
                action=IncidentActionType.MARK_ARRIVAL,
                status=IncidentActionType.MARK_ARRIVAL.value,
                is_system=False,
                created_at=event_at + timedelta(seconds=reaction_seconds),
            ),
        ],
        activities=[
            IncidentActivity(
                kind="TRAINING_BRIGADE",
                stage="ARRIVED",
                body="Прибыли к месту",
                service_name="Бригада 101",
                event_key="brigade-101:ARRIVED",
                created_at=event_at,
            )
        ],
    )

    result = assess_run(TrainingRun(id=7), [incident], [], [])
    step = result.metrics["card_results"][0]["brigade"][0]

    assert step["seconds"] == reaction_seconds
    assert step["severity"] == expected_severity
    assert result.metrics["major_errors"] == expected_major_errors
    assert result.metrics["critical_signals"] == 0


def test_same_timestamp_brigade_events_do_not_hide_later_matching_actions():
    start = datetime(2026, 9, 24, 18, tzinfo=UTC)
    event_at = start + timedelta(seconds=60)
    incident = Incident(
        id=15,
        incident_number="КП-15",
        delivered_at=start,
        primary_status_at=start + timedelta(seconds=1),
        lifecycle_state=IncidentLifecycleState.OPENED,
        dds_status=DDSResponseStatus.ARRIVED,
        actions=[
            IncidentAction(
                action=IncidentActionType.ACCEPT,
                status=IncidentActionType.ACCEPT.value,
                is_system=False,
                created_at=start + timedelta(seconds=1),
            ),
            IncidentAction(
                action=IncidentActionType.START_RESPONSE,
                status=IncidentActionType.START_RESPONSE.value,
                is_system=False,
                created_at=event_at + timedelta(seconds=10),
            ),
            IncidentAction(
                action=IncidentActionType.MARK_ARRIVAL,
                status=IncidentActionType.MARK_ARRIVAL.value,
                is_system=False,
                created_at=event_at + timedelta(seconds=20),
            ),
        ],
        activities=[
            IncidentActivity(
                kind="TRAINING_BRIGADE",
                stage="EN_ROUTE",
                body="Выехали к месту",
                service_name="Бригада 101",
                event_key="brigade-101:EN_ROUTE",
                created_at=event_at,
            ),
            IncidentActivity(
                kind="TRAINING_BRIGADE",
                stage="ARRIVED",
                body="Прибыли к месту",
                service_name="Бригада 101",
                event_key="brigade-101:ARRIVED",
                created_at=event_at,
            ),
        ],
    )

    result = assess_run(TrainingRun(id=7), [incident], [], [])
    brigade = result.metrics["card_results"][0]["brigade"]

    assert [step["seconds"] for step in brigade] == [10, 20]
    assert [step["severity"] for step in brigade] == ["OK", "OK"]
    assert result.metrics["major_errors"] == 0
    assert result.metrics["critical_signals"] == 0
