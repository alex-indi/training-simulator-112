"""Серверные факты виртуальных служб и учебной бригады 101."""

from datetime import datetime
from hashlib import sha1

from app.modules.incidents.models import Incident, IncidentActionType, IncidentActivity
from app.modules.training.clock import active_seconds
from app.modules.training.models import TrainingRun, TrainingSession

# Этапы разнесены так, чтобы у ДДС был полный 45-секундный норматив реакции
# на каждое сообщение бригады и следующее сообщение не сужало фактическое окно.
BRIGADE_STAGES = (
    ("EN_ROUTE", 15, "Выехали к месту"),
    ("ARRIVED", 75, "Прибыли к месту"),
    ("WORKING", 135, "Приступили к работам"),
    ("COMPLETED", 195, "Работы завершены"),
)


def _service_number(name: str) -> str | None:
    for number in ("101", "102", "103"):
        if name.startswith(f"Служба {number}") or number in name.split():
            return number
    return None


def classifier_services(incident: Incident) -> list[tuple[int | None, str, str]]:
    """Возвращает краткие имена служб из snapshot, не читая меняющийся справочник."""
    rows = incident.source_snapshot.get("scenario_services") or []
    if rows:
        source = [(row.get("service_id"), row.get("name", "")) for row in rows]
    else:
        source = [(None, name) for name in incident.source_snapshot.get("notified_services", [])]
    services = []
    seen = set()
    for service_id, name in source:
        number = _service_number(name)
        key = number or str(service_id or sha1(name.encode()).hexdigest()[:12])
        if key not in seen:
            services.append(
                (service_id, f"Служба {number}" if number else name.split(" (")[0][:200], key)
            )
            seen.add(key)
    return services


def record_other_service_reactions(incident: Incident, now: datetime) -> None:
    """Моделирует воспроизводимый первичный ответ остальных служб после принятия ДДС 101."""
    if not any(number == "101" for _, _, number in classifier_services(incident)):
        return
    existing = {activity.event_key for activity in incident.activities}
    for service_id, name, number in classifier_services(incident):
        if number == "101":
            continue
        key = f"other-service:{number}"
        if key in existing:
            continue
        # В MVP реакция других служб детерминирована: если служба входит в snapshot
        # карточки, она принимает карточку. Отказы позже можно задавать явным фактом
        # сценария, но они не должны зависеть от runtime id происшествия.
        incident.activities.append(
            IncidentActivity(
                event_key=key,
                kind="OTHER_SERVICE",
                service_id=service_id,
                service_name=name,
                stage="ACCEPTED",
                body="Карточка принята",
                created_at=now,
            )
        )


def release_brigade_stages(
    incident: Incident, session: TrainingSession, run: TrainingRun | None, now: datetime
) -> bool:
    """Выпускает этапы по учебному времени, не меняя статус ДДС."""
    if not any(number == "101" for _, _, number in classifier_services(incident)):
        return False
    accepted = next(
        (
            action.created_at
            for action in incident.actions
            if action.action == IncidentActionType.ACCEPT
        ),
        None,
    )
    if accepted is None:
        return False
    elapsed = active_seconds(accepted, now, session.pauses, run.pauses if run else [])
    existing = {activity.event_key for activity in incident.activities}
    changed = False
    for stage, offset, body in BRIGADE_STAGES:
        key = f"brigade-101:{stage}"
        if elapsed < offset or key in existing:
            continue
        if "пожар" in incident.incident_type.lower():
            if stage == "WORKING":
                body = "Приступили к тушению"
            elif stage == "COMPLETED":
                body = "Пожар ликвидирован"
        incident.activities.append(
            IncidentActivity(
                event_key=key,
                kind="TRAINING_BRIGADE",
                service_name="Бригада 101",
                stage=stage,
                body=body,
                created_at=now,
            )
        )
        changed = True
    return changed
