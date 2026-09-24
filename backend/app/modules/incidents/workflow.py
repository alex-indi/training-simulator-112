"""Доменные команды lifecycle готовой карточки происшествия."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.modules.incidents.models import (
    DDSResponseStatus,
    DdsServiceEventType,
    Incident,
    IncidentAction,
    IncidentActionType,
    IncidentLifecycleState,
)


class InvalidIncidentTransitionError(ValueError):
    """Действие недопустимо из текущего статуса ДДС."""


class IncidentActionCommentRequiredError(ValueError):
    """Для действия требуется непустой комментарий диспетчера."""


ACTION_STATUSES = {
    IncidentActionType.ACCEPT: DDSResponseStatus.ACCEPTED,
    IncidentActionType.REJECT: DDSResponseStatus.REJECTED,
    IncidentActionType.START_RESPONSE: DDSResponseStatus.RESPONSE_STARTED,
    IncidentActionType.MARK_ARRIVAL: DDSResponseStatus.ARRIVED,
    IncidentActionType.START_WORK: DDSResponseStatus.WORKING,
    IncidentActionType.COMPLETE_WORK: DDSResponseStatus.COMPLETED,
    IncidentActionType.REFUSE_WORK: DDSResponseStatus.WORK_REFUSED,
}

PROGRESS_ACTIONS = (
    IncidentActionType.START_RESPONSE,
    IncidentActionType.MARK_ARRIVAL,
    IncidentActionType.START_WORK,
    IncidentActionType.COMPLETE_WORK,
    IncidentActionType.REFUSE_WORK,
)

COMMENT_REQUIRED_ACTIONS = {
    IncidentActionType.REJECT,
    IncidentActionType.REFUSE_WORK,
}


def get_available_actions(incident: Incident) -> list[IncidentActionType]:
    """Возвращает ещё не записанные команды согласно правилам АРМ-112."""
    performed_actions = {
        entry.action for entry in incident.actions if entry.action is not None
    }
    if performed_actions & {
        IncidentActionType.COMPLETE_WORK,
        IncidentActionType.REFUSE_WORK,
    }:
        return []

    if IncidentActionType.ACCEPT not in performed_actions:
        if IncidentActionType.REJECT in performed_actions:
            return [IncidentActionType.ACCEPT]
        return [IncidentActionType.ACCEPT, IncidentActionType.REJECT]

    return [action for action in PROGRESS_ACTIONS if action not in performed_actions]


def _append_system_event(
    incident: Incident,
    *,
    event_type: DdsServiceEventType,
    created_at: datetime,
    actor_user_id: int | None = None,
    actor_display_name: str = "Система-112",
) -> IncidentAction:
    entry = IncidentAction(
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        is_system=True,
        status=event_type.value,
        action=None,
        from_status=None,
        to_status=None,
        comment=None,
        created_at=created_at,
    )
    incident.actions.append(entry)
    return entry


def create_delivered_incident(
    *,
    training_session_id: int,
    source_snapshot: dict[str, Any],
    server_time: datetime | None = None,
) -> Incident:
    """Создаёт независимый snapshot карточки и фиксирует серверное время доставки."""
    delivered_at = server_time or datetime.now(UTC)
    snapshot = deepcopy(source_snapshot)
    if snapshot.pop("reported_at_mode", None) == "DELIVERY":
        snapshot["reported_at"] = delivered_at.isoformat()

    incident = Incident(
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
        dds_status=DDSResponseStatus.AWAITING_DECISION,
        created_at=delivered_at,
        delivered_at=delivered_at,
    )
    _append_system_event(
        incident,
        event_type=DdsServiceEventType.SERVICE_ADDED,
        created_at=delivered_at,
        actor_display_name="Virtual112",
    )
    return incident


def mark_incident_opened(
    incident: Incident,
    *,
    actor_user_id: int | None = None,
    actor_display_name: str = "Система-112",
    server_time: datetime | None = None,
) -> Incident:
    """Идемпотентно фиксирует первое открытие карточки серверным временем."""
    if incident.opened_at is not None:
        return incident

    incident.opened_at = server_time or datetime.now(UTC)
    if incident.lifecycle_state != IncidentLifecycleState.FINISHED:
        incident.lifecycle_state = IncidentLifecycleState.OPENED
    _append_system_event(
        incident,
        event_type=DdsServiceEventType.SERVICE_RECEIVED,
        created_at=incident.opened_at,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )
    return incident


def perform_incident_action(
    incident: Incident,
    *,
    action: IncidentActionType,
    actor_user_id: int,
    actor_display_name: str,
    comment: str | None = None,
    server_time: datetime | None = None,
) -> IncidentAction:
    """Проверяет переход, меняет статус и добавляет запись истории атомарно."""
    available_actions = get_available_actions(incident)
    if action not in available_actions:
        raise InvalidIncidentTransitionError(
            f"Действие {action.value} недоступно из текущего состояния карточки"
        )

    normalized_comment = comment.strip() if comment else None
    if action in COMMENT_REQUIRED_ACTIONS and not normalized_comment:
        raise IncidentActionCommentRequiredError(
            "Для выбранного действия требуется комментарий"
        )

    from_status = incident.dds_status
    to_status = ACTION_STATUSES[action]
    created_at = server_time or datetime.now(UTC)
    history_entry = IncidentAction(
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        is_system=False,
        status=to_status.value,
        action=action,
        from_status=from_status,
        to_status=to_status,
        comment=normalized_comment,
        created_at=created_at,
    )
    incident.dds_status = to_status
    if action in {IncidentActionType.COMPLETE_WORK, IncidentActionType.REFUSE_WORK}:
        incident.lifecycle_state = IncidentLifecycleState.FINISHED
        incident.finished_at = created_at
    if incident.primary_status_at is None and action in {
        IncidentActionType.ACCEPT,
        IncidentActionType.REJECT,
    }:
        incident.primary_status_at = created_at
    incident.actions.append(history_entry)
    return history_entry
