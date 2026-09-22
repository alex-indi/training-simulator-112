"""Доменная команда доставки готовой карточки происшествия."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.modules.incidents.models import Incident, IncidentLifecycleState


def create_delivered_incident(
    *,
    training_session_id: int,
    source_snapshot: dict[str, Any],
    server_time: datetime | None = None,
) -> Incident:
    """Создаёт независимый snapshot карточки и фиксирует серверное время доставки."""
    delivered_at = server_time or datetime.now(UTC)
    snapshot = deepcopy(source_snapshot)

    return Incident(
        training_session_id=training_session_id,
        incident_number=snapshot["incident_number"],
        reported_at=datetime.fromisoformat(snapshot["reported_at"]),
        source=snapshot["source"],
        applicant_name=snapshot.get("applicant_name"),
        applicant_phone=snapshot.get("applicant_phone"),
        address=snapshot["address"],
        latitude=snapshot.get("latitude"),
        longitude=snapshot.get("longitude"),
        description=snapshot["description"],
        incident_type=snapshot["incident_type"],
        source_snapshot=snapshot,
        lifecycle_state=IncidentLifecycleState.DELIVERED,
        created_at=delivered_at,
        delivered_at=delivered_at,
    )
