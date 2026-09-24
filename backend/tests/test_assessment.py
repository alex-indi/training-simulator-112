"""Расчёт предварительного результата по фактической истории занятия."""

from datetime import UTC, datetime, timedelta

from app.modules.incidents.models import (
    DDSResponseStatus,
    Incident,
    IncidentAction,
    IncidentActionType,
    IncidentLifecycleState,
)
from app.modules.response.models import ResponseAssignment, ResponseMessage, ResponseMessageSender
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
        response_assignments=[
            ResponseAssignment(
                messages=[
                    ResponseMessage(
                        sender_type=ResponseMessageSender.RESPONSE_UNIT,
                        body="Прибыли",
                        created_at=start + timedelta(seconds=20),
                        read_at=None,
                    )
                ]
            )
        ],
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
    assert {item.kind for item in result.deviations} == {"POSSIBLE_REFUSAL", "UNREAD_MESSAGE"}
    assert result.automatic_score == 90

    result.deviations[0].decision = "DISMISSED"
    assert _score(result) == 96
    assert result.automatic_score == 90


def test_assessment_flags_unfinished_card_without_primary_decision():
    start = datetime(2026, 9, 24, 10, tzinfo=UTC)
    incident = Incident(
        id=12,
        incident_number="КП-12",
        delivered_at=start,
        lifecycle_state=IncidentLifecycleState.DELIVERED,
        dds_status=DDSResponseStatus.AWAITING_DECISION,
        actions=[],
        response_assignments=[],
    )
    result = assess_run(TrainingRun(id=7), [incident], [], [])
    assert {item.kind for item in result.deviations} == {"NO_PRIMARY_STATUS", "UNFINISHED"}
    assert result.metrics["critical_signals"] == 1
    assert result.automatic_score == 82
