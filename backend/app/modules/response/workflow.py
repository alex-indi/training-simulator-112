"""Переходы фактического состояния виртуальной группы."""

from datetime import UTC, datetime

from app.modules.response.models import (
    ResponseAssignment,
    ResponseAssignmentEvent,
    ResponseAssignmentState,
    ResponseUnit,
)


class InvalidResponseTransitionError(ValueError):
    """Сценарное событие не соответствует текущему состоянию назначения."""


NEXT_STATES = {
    ResponseAssignmentState.ASSIGNED: {ResponseAssignmentState.ACKNOWLEDGED},
    ResponseAssignmentState.ACKNOWLEDGED: {ResponseAssignmentState.EN_ROUTE},
    ResponseAssignmentState.EN_ROUTE: {ResponseAssignmentState.ARRIVED},
    ResponseAssignmentState.ARRIVED: {ResponseAssignmentState.WORKING},
    ResponseAssignmentState.WORKING: {ResponseAssignmentState.COMPLETED},
}


def create_assignment(
    *,
    incident_id: int,
    training_run_id: int,
    response_unit: ResponseUnit,
    actor_user_id: int,
    server_time: datetime | None = None,
) -> ResponseAssignment:
    """Создаёт назначение с первой неизменяемой записью истории."""
    now = server_time or datetime.now(UTC)
    assignment = ResponseAssignment(
        incident_id=incident_id,
        training_run_id=training_run_id,
        response_unit=response_unit,
        state=ResponseAssignmentState.ASSIGNED,
        assigned_at=now,
        state_changed_at=now,
    )
    assignment.events.append(
        ResponseAssignmentEvent(
            from_state=None,
            to_state=ResponseAssignmentState.ASSIGNED,
            event_key="assigned",
            actor_user_id=actor_user_id,
            created_at=now,
        )
    )
    return assignment


def apply_scenario_event(
    assignment: ResponseAssignment,
    *,
    target_state: ResponseAssignmentState,
    event_key: str,
    server_time: datetime | None = None,
) -> ResponseAssignmentEvent:
    """Идемпотентно применяет подготовленное событие сценария."""
    for event in assignment.events:
        if event.event_key == event_key:
            if event.to_state != target_state:
                raise InvalidResponseTransitionError(
                    "Ключ события уже использован для другого перехода"
                )
            return event

    allowed = NEXT_STATES.get(assignment.state, set())
    if assignment.state in NEXT_STATES:
        allowed = allowed | {ResponseAssignmentState.CANCELLED}
    if target_state not in allowed:
        raise InvalidResponseTransitionError(
            f"Переход {assignment.state.value} → {target_state.value} недоступен"
        )

    now = server_time or datetime.now(UTC)
    event = ResponseAssignmentEvent(
        from_state=assignment.state,
        to_state=target_state,
        event_key=event_key,
        actor_user_id=None,
        created_at=now,
    )
    assignment.state = target_state
    assignment.state_changed_at = now
    assignment.events.append(event)
    return event
