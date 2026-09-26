"""Расчёт предварительного результата по фактической истории занятия."""

from datetime import UTC, datetime, timedelta

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
            IncidentAction(action=action, status=action.value, is_system=False,
                           created_at=start + timedelta(seconds=offset))
            for action, offset in actions
        ],
        activities=[
            IncidentActivity(kind="TRAINING_BRIGADE", stage=stage, body=body,
                             service_name="Бригада 101", event_key=f"brigade-101:{stage}",
                             created_at=start + timedelta(seconds=offset))
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
