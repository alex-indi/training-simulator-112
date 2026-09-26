"""Первичные ответы служб и независимый от статуса ДДС ход работы бригады."""

from datetime import UTC, datetime, timedelta

from app.modules.incidents.activity import (
    record_other_service_reactions,
    release_brigade_stages,
)
from app.modules.incidents.models import DDSResponseStatus, IncidentActionType
from app.modules.incidents.workflow import create_delivered_incident, perform_incident_action
from app.modules.response import models as response_models  # noqa: F401
from app.modules.scenario_library import instance_models as scenario_instance_models  # noqa: F401
from app.modules.training.models import TrainingRun, TrainingSession


def _incident(incident_id: int):
    start = datetime(2026, 9, 26, 12, tzinfo=UTC)
    incident = create_delivered_incident(
        training_session_id=1,
        server_time=start,
        source_snapshot={
            "incident_number": f"СЦ-{incident_id}",
            "reported_at": start.isoformat(),
            "source": "SCENARIO_INSTANCE",
            "address": "Москва, Учебная, 1",
            "description": "Пожар в школе",
            "incident_type": "Пожар",
            "scenario_services": [
                {"service_id": 11, "name": "Служба 101 (пожарная охрана)"},
                {"service_id": 12, "name": "Служба 102 (полиция)"},
                {"service_id": 13, "name": "Служба 103 (скорая помощь)"},
            ],
        },
    )
    incident.id = incident_id
    return incident, start


def test_virtual_reactions_and_brigade_stages_preserve_dds_status():
    incident, start = _incident(2)
    accepted_at = start + timedelta(seconds=3)
    perform_incident_action(
        incident,
        action=IncidentActionType.ACCEPT,
        actor_user_id=1,
        actor_display_name="Диспетчер 101",
        server_time=accepted_at,
    )
    record_other_service_reactions(incident, accepted_at)
    record_other_service_reactions(incident, accepted_at)
    assert [(item.service_name, item.stage, item.created_at) for item in incident.activities] == [
        ("Служба 102", "ACCEPTED", accepted_at),
        ("Служба 103", "REJECTED", accepted_at),
    ]

    session = TrainingSession(id=1)
    run = TrainingRun(id=1)
    assert not release_brigade_stages(incident, session, run, accepted_at + timedelta(seconds=9))
    assert release_brigade_stages(incident, session, run, accepted_at + timedelta(seconds=10))
    assert release_brigade_stages(incident, session, run, accepted_at + timedelta(seconds=70))
    assert not release_brigade_stages(incident, session, run, accepted_at + timedelta(seconds=80))
    brigade = [item for item in incident.activities if item.kind == "TRAINING_BRIGADE"]
    assert [item.stage for item in brigade] == ["EN_ROUTE", "ARRIVED", "WORKING", "COMPLETED"]
    assert brigade[-1].body == "Пожар ликвидирован"
    assert brigade[0].created_at == accepted_at + timedelta(seconds=10)
    assert incident.dds_status == DDSResponseStatus.ACCEPTED
    assert incident.finished_at is None


def test_brigade_waits_for_acceptance():
    incident, start = _incident(1)
    session = TrainingSession(id=1)
    assert not release_brigade_stages(
        incident, session, TrainingRun(id=1), start + timedelta(hours=1)
    )
    assert incident.activities == []


def test_other_classifier_service_gets_only_primary_reaction():
    incident, start = _incident(1)
    incident.source_snapshot["scenario_services"].append(
        {"service_id": 14, "name": "Городская служба газа (дежурная часть)"}
    )
    record_other_service_reactions(incident, start)
    gas = next(item for item in incident.activities if item.service_id == 14)
    assert gas.service_name == "Городская служба газа"
    assert gas.stage == "ACCEPTED"
    assert gas.event_key == "other-service:14"
