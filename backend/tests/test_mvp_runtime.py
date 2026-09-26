"""Критичные инварианты упрощённого runtime ДДС 101."""

from datetime import UTC, datetime, timedelta

from app.modules.incidents.activity import (
    BRIGADE_STAGES,
    record_other_service_reactions,
)
from app.modules.incidents.models import (
    DDSResponseStatus,
    Incident,
    IncidentAction,
    IncidentActionType,
    IncidentActivity,
    IncidentLifecycleState,
)
from app.modules.training.assessment import BRIGADE_REACTION_LIMIT_SECONDS, assess_run
from app.modules.training.models import TrainingRun


def _incident_with_brigade_response(delay_seconds: int) -> Incident:
    start = datetime(2026, 9, 26, 12, tzinfo=UTC)
    event_at = start + timedelta(seconds=60)
    response_at = event_at + timedelta(seconds=delay_seconds)
    return Incident(
        id=100 + delay_seconds,
        incident_number=f"КП-{delay_seconds}",
        delivered_at=start,
        primary_status_at=start + timedelta(seconds=5),
        lifecycle_state=IncidentLifecycleState.OPENED,
        dds_status=DDSResponseStatus.RESPONSE_STARTED,
        actions=[
            IncidentAction(
                action=IncidentActionType.ACCEPT,
                status="ACCEPTED",
                is_system=False,
                created_at=start + timedelta(seconds=5),
            ),
            IncidentAction(
                action=IncidentActionType.START_RESPONSE,
                status="RESPONSE_STARTED",
                is_system=False,
                created_at=response_at,
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
            )
        ],
    )


def test_brigade_stages_leave_full_assessment_window() -> None:
    offsets = [offset for _, offset, _ in BRIGADE_STAGES]
    assert offsets == sorted(offsets)
    assert all(
        current - previous > BRIGADE_REACTION_LIMIT_SECONDS
        for previous, current in zip(offsets, offsets[1:], strict=False)
    )


def test_assessment_accepts_full_45_second_brigade_window() -> None:
    result = assess_run(TrainingRun(id=1), [_incident_with_brigade_response(45)], [], [])
    brigade = result.metrics["card_results"][0]["brigade"][0]
    assert brigade["seconds"] == 45
    assert brigade["severity"] == "OK"
    assert not any(item.kind == "SLOW_BRIGADE_REACTION" for item in result.deviations)


def test_assessment_marks_46_second_brigade_response_as_slow() -> None:
    result = assess_run(TrainingRun(id=1), [_incident_with_brigade_response(46)], [], [])
    brigade = result.metrics["card_results"][0]["brigade"][0]
    assert brigade["seconds"] == 46
    assert brigade["severity"] == "MAJOR"
    assert any(item.kind == "SLOW_BRIGADE_REACTION" for item in result.deviations)


def test_other_service_reaction_does_not_depend_on_incident_id() -> None:
    now = datetime(2026, 9, 26, 12, tzinfo=UTC)
    snapshot = {
        "scenario_services": [
            {"service_id": 1, "name": "Служба 101"},
            {"service_id": 2, "name": "Служба 103"},
        ]
    }
    incidents = [
        Incident(id=10, source_snapshot=snapshot, activities=[]),
        Incident(id=11, source_snapshot=snapshot, activities=[]),
    ]

    for incident in incidents:
        record_other_service_reactions(incident, now)
        assert len(incident.activities) == 1
        assert incident.activities[0].service_name == "Служба 103"
        assert incident.activities[0].stage == "ACCEPTED"
        assert incident.activities[0].body == "Карточка принята"
