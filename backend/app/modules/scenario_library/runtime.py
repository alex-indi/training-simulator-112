"""Bridge immutable scenario content into the existing queue and incident runtime."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.incidents.models import Incident
from app.modules.incidents.schemas import IncidentSnapshot
from app.modules.response.models import (
    ResponseAssignment,
    ResponseAssignmentState,
    ResponseMessage,
    ResponseMessageSender,
)
from app.modules.response.workflow import apply_scenario_event
from app.modules.scenario_library.instance_models import (
    ScenarioInstance,
    ScenarioInstanceEvent,
    ScenarioRuntimeEvent,
)
from app.modules.training.clock import active_seconds
from app.modules.training.models import ScenarioEvent, TrainingRun, TrainingSession

RESPONSE_STATE_ORDER = {
    state: index
    for index, state in enumerate(
        (
            ResponseAssignmentState.ASSIGNED,
            ResponseAssignmentState.ACKNOWLEDGED,
            ResponseAssignmentState.EN_ROUTE,
            ResponseAssignmentState.ARRIVED,
            ResponseAssignmentState.WORKING,
            ResponseAssignmentState.COMPLETED,
        )
    )
}


def incident_snapshot(instance: ScenarioInstance) -> dict:
    """Only initial, trainee-visible facts cross the boundary into Incident."""
    initial = instance.initial_state_snapshot
    obj = instance.object_snapshot
    classifier = instance.classifier_snapshot
    description = initial.get("render", {}).get("rendered_text") or initial["description"]
    if not initial.get("render") and initial.get("caller_text"):
        description = f"{description}\n{initial['caller_text']}"
    snapshot = IncidentSnapshot(
        incident_number=f"СЦ-{instance.id}",
        reported_at=datetime.now(UTC),
        source="SCENARIO_INSTANCE",
        address=obj.get("address") or obj["name"],
        latitude=float(obj["latitude"]) if obj.get("latitude") is not None else None,
        longitude=float(obj["longitude"]) if obj.get("longitude") is not None else None,
        description=description,
        incident_type=classifier["final_incident_type"],
        features=[item["name"] for item in classifier.get("features", [])],
    ).model_dump(mode="json")
    snapshot["reported_at_mode"] = "DELIVERY"
    snapshot["object_context"] = {
        key: obj.get(key) for key in ("name", "district", "administrative_area")
    }
    snapshot["classifier_snapshot"] = {
        key: classifier.get(key)
        for key in ("source_code", "source_reference", "incident_group", "final_incident_type")
    }
    snapshot["scenario_services"] = [
        {
            "service_id": service["service_id"],
            "name": service["official_name"],
        }
        for service in instance.service_snapshot
        if "service_id" in service
    ]
    return snapshot


async def prepare_runtime_events(database: AsyncSession, incident: Incident) -> None:
    """Create pending events within the same transaction as Incident delivery."""
    if incident.scenario_instance_id is None:
        return
    rows = (
        await database.scalars(
            select(ScenarioInstanceEvent)
            .where(ScenarioInstanceEvent.scenario_instance_id == incident.scenario_instance_id)
            .order_by(ScenarioInstanceEvent.sequence_number)
        )
    ).all()
    for row in rows:
        if row.event_type == "INITIAL_REPORT":
            continue
        database.add(
            ScenarioRuntimeEvent(
                incident_id=incident.id,
                scenario_instance_event_id=row.id,
                event_type=row.event_type,
                offset_seconds=row.offset_seconds,
                payload_snapshot=dict(row.payload_snapshot),
            )
        )


async def release_due_events(
    database: AsyncSession, session: TrainingSession, now: datetime
) -> tuple[list[int], list[tuple[ResponseMessage, int]], list[int]]:
    """Release planned facts using the session's existing server clock and pause records."""
    if session.paused_at or session.finish_mode:
        return [], [], []
    rows = (
        await database.scalars(
            select(ScenarioRuntimeEvent)
            .join(Incident, Incident.id == ScenarioRuntimeEvent.incident_id)
            .where(
                Incident.training_session_id == session.id,
                ScenarioRuntimeEvent.status == "PENDING",
            )
            .options(selectinload(ScenarioRuntimeEvent.incident))
            .order_by(ScenarioRuntimeEvent.offset_seconds, ScenarioRuntimeEvent.id)
        )
    ).all()
    runs = {run.id: run for run in session.runs}
    released = []
    messages = []
    state_changed = []
    for row in rows:
        incident = row.incident
        run_id = incident.training_run_id or incident.claimed_by_training_run_id
        run: TrainingRun | None = runs.get(run_id)
        if incident.training_group_id and incident.claimed_by_training_run_id is None:
            continue
        if run and run.paused_at:
            continue
        if (
            active_seconds(incident.delivered_at, now, session.pauses, run.pauses if run else [])
            < row.offset_seconds
        ):
            continue
        instance = await database.get(ScenarioInstance, incident.scenario_instance_id)
        body = (
            row.payload_snapshot.get("render", {}).get("rendered_text")
            or row.payload_snapshot.get("description")
            or row.payload_snapshot.get("title")
            or row.event_type
        )
        assignment = None
        if row.event_type == "RESPONSE_MESSAGE":
            target_service_id = row.payload_snapshot.get("target_service_id")
            if target_service_id is None:
                continue
            assignment = await database.scalar(
                select(ResponseAssignment)
                .where(
                    ResponseAssignment.incident_id == incident.id,
                    ResponseAssignment.dispatch_service_id == target_service_id,
                )
                .options(selectinload(ResponseAssignment.events))
            )
            if assignment is None:
                continue
            target_state = row.payload_snapshot.get("target_response_state")
            if target_state is not None:
                planned = ResponseAssignmentState(target_state)
                if (
                    assignment.state in RESPONSE_STATE_ORDER
                    and RESPONSE_STATE_ORDER[assignment.state] < RESPONSE_STATE_ORDER[planned]
                ):
                    apply_scenario_event(
                        assignment,
                        target_state=planned,
                        event_key=f"scenario-state:{row.scenario_instance_event_id}",
                        server_time=now,
                    )
                    state_changed.append(incident.id)
        if row.event_type not in {"SYSTEM_EVENT", "RESPONSE_MESSAGE"}:
            database.add(
                ScenarioEvent(
                    incident_id=incident.id,
                    instructor_id=instance.created_by_user_id,
                    origin="SCENARIO",
                    scenario_instance_event_id=row.scenario_instance_event_id,
                    kind=row.event_type,
                    body=body,
                    created_at=now,
                )
            )
        if assignment is not None:
            message = ResponseMessage(
                response_assignment_id=assignment.id,
                sender_type=ResponseMessageSender.RESPONSE_UNIT,
                body=body,
                event_key=f"scenario:{row.scenario_instance_event_id}",
                created_at=now,
            )
            database.add(message)
            recipient = runs[assignment.training_run_id].trainee_id
            messages.append((message, recipient))
        row.status = "RELEASED"
        row.released_at = now
        released.append(incident.id)
    return list(set(released)), messages, list(set(state_changed))
