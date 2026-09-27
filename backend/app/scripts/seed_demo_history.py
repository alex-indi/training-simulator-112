"""Два демонстрационных завершённых занятия с настоящими связями runtime-моделей."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.modules.admin.models import UserGroup
from app.modules.identity.models import User
from app.modules.incidents.activity import BRIGADE_STAGES, record_other_service_reactions
from app.modules.incidents.models import (
    Incident,
    IncidentActionType,
    IncidentActivity,
    IncidentLifecycleState,
)
from app.modules.incidents.schemas import IncidentSnapshot
from app.modules.incidents.workflow import (
    create_delivered_incident,
    mark_incident_opened,
    perform_incident_action,
)
from app.modules.response.models import (
    ResponseAssignment,
    ResponseAssignmentEvent,
    ResponseAssignmentState,
    ResponseMessage,
    ResponseMessageSender,
    ResponseUnit,
)
from app.modules.scenario_library.instance_models import SavedIncidentCard
from app.modules.training.models import (
    AssessmentAudit,
    DeliveryState,
    InstructorNote,
    QueueMode,
    ScenarioQueueItem,
    TrainingGroup,
    TrainingMode,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
)

SEED_PATH = Path(__file__).resolve().parents[2] / "seed" / "demo" / "completed_sessions.json"


def load_sessions() -> list[dict]:
    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    codes = (
        [row.get("seed_code") for row in rows if isinstance(row, dict)]
        if isinstance(rows, list) else []
    )
    if not codes or len(codes) != len(rows) or len(codes) != len(set(codes)):
        raise ValueError("completed_sessions.json: нужны уникальные seed_code")
    for row in rows:
        if len({case["card"] for case in row["cases"]}) != len(row["cases"]):
            raise ValueError(f"Повторная карточка в {row['seed_code']}")
    return rows


def _at(start: datetime, seconds: int) -> datetime:
    return start + timedelta(seconds=seconds)


def _incident_snapshot(card: SavedIncidentCard, number: str, delivered: datetime) -> dict:
    content = card.snapshot
    initial = content["initial_state_snapshot"]
    obj = content["object_snapshot"]
    classifier = content["classifier_snapshot"]
    snapshot = IncidentSnapshot(
        incident_number=number,
        reported_at=delivered,
        source="SCENARIO_INSTANCE",
        address=obj.get("address") or obj["name"],
        latitude=float(obj["latitude"]) if obj.get("latitude") else None,
        longitude=float(obj["longitude"]) if obj.get("longitude") else None,
        description=initial["render"]["rendered_text"],
        incident_type=classifier["final_incident_type"],
        features=[item["name"] for item in classifier.get("features", [])],
    ).model_dump(mode="json")
    snapshot["object_context"] = {
        key: obj.get(key) for key in ("name", "district", "administrative_area")
    }
    snapshot["scenario_services"] = [
        {"service_id": item["service_id"], "name": item["official_name"]}
        for item in content["service_snapshot"]
    ]
    snapshot["demo_seed_code"] = content["template_snapshot"]["demo_seed_code"]
    return snapshot


async def _create_case(db, session, run, trainee, card, unit, case, index, start):
    from app.modules.training.assessment import BRIGADE_ACTIONS

    delivered = _at(start, case["offset"])
    snapshot = _incident_snapshot(card, f"ДЕМО-{session.id:03d}-{index:02d}", delivered)
    incident = create_delivered_incident(
        training_session_id=session.id, source_snapshot=snapshot, server_time=delivered
    )
    incident.activities = []
    incident.training_run_id = run.id
    incident.claimed_by_training_run_id = run.id
    incident.training_group_id = run.group_id
    incident.claimed_at = _at(delivered, 3)
    mark_incident_opened(
        incident, actor_user_id=trainee.id, actor_display_name=trainee.full_name,
        server_time=_at(delivered, 5),
    )
    db.add(incident)
    await db.flush()
    db.add(ScenarioQueueItem(
        training_session_id=session.id,
        training_run_id=run.id,
        title=card.name[:200],
        snapshot=snapshot,
        position=index,
        delivery_position=index,
        approved=True,
        delivery_state=DeliveryState.DELIVERED,
        delivered_at=delivered,
        incident_id=incident.id,
    ))
    accepted = _at(delivered, case["decision_delay"])
    perform_incident_action(
        incident, action=IncidentActionType.ACCEPT,
        actor_user_id=trainee.id, actor_display_name=trainee.full_name,
        server_time=accepted,
    )
    record_other_service_reactions(incident, _at(accepted, 7))
    assignment = ResponseAssignment(
        incident_id=incident.id,
        response_unit_id=unit.id,
        dispatch_service_id=snapshot["scenario_services"][0]["service_id"],
        training_run_id=run.id,
        state=ResponseAssignmentState.COMPLETED,
        assigned_at=accepted,
        state_changed_at=_at(accepted, 195),
    )
    db.add(assignment)
    await db.flush()
    db.add(ResponseAssignmentEvent(
        response_assignment_id=assignment.id,
        from_state=ResponseAssignmentState.ASSIGNED,
        to_state=ResponseAssignmentState.ACKNOWLEDGED,
        event_key=f"demo:{session.id}:{index}:ACKNOWLEDGED",
        created_at=_at(accepted, 5),
    ))
    db.add(ResponseMessage(
        response_assignment_id=assignment.id,
        sender_type=ResponseMessageSender.DISPATCHER,
        body=case["dispatch_message"],
        actor_user_id=trainee.id,
        event_key=f"demo:{session.id}:{index}:dispatcher",
        created_at=_at(accepted, 3),
    ))
    for stage_index, (stage, seconds, body) in enumerate(BRIGADE_STAGES):
        event_at = _at(accepted, seconds)
        state = ResponseAssignmentState(stage)
        previous = (
            ResponseAssignmentState.ACKNOWLEDGED if stage_index == 0
            else ResponseAssignmentState(BRIGADE_STAGES[stage_index - 1][0])
        )
        db.add(ResponseAssignmentEvent(
            response_assignment_id=assignment.id,
            from_state=previous,
            to_state=state,
            event_key=f"demo:{session.id}:{index}:{stage}",
            created_at=event_at,
        ))
        if "пожар" in incident.incident_type.lower():
            if stage == "WORKING":
                body = "Приступили к тушению, проверяем смежные помещения"
            elif stage == "COMPLETED":
                body = "Пожар ликвидирован, проводится контрольная проверка"
        incident.activities.append(IncidentActivity(
            event_key=f"brigade-101:{stage}",
            kind="TRAINING_BRIGADE",
            service_name="Бригада 101",
            stage=stage,
            body=body,
            created_at=event_at,
        ))
        db.add(ResponseMessage(
            response_assignment_id=assignment.id,
            sender_type=ResponseMessageSender.RESPONSE_UNIT,
            body=body,
            event_key=f"demo:{session.id}:{index}:{stage}",
            created_at=event_at,
        ))
        delay = case["stage_delays"][stage_index]
        if delay:
            perform_incident_action(
                incident,
                action=BRIGADE_ACTIONS[stage],
                actor_user_id=trainee.id,
                actor_display_name=trainee.full_name,
                order_number=f"Н-{session.id:03d}-{index:02d}",
                server_time=_at(event_at, delay),
            )
    if case["outcome"] == "UNFINISHED":
        incident.lifecycle_state = IncidentLifecycleState.OPENED
    return incident


async def seed_demo_history() -> dict[str, int]:
    from app.modules.training.assessment import assess_run

    engine = create_database_engine(get_settings())
    stats = {"created": 0, "unchanged": 0}
    try:
        factory = create_session_factory(engine)
        async with factory() as db:
            users = {row.username: row for row in (await db.scalars(select(User))).all()}
            instructor = users["instructor"]
            groups = {
                row.code: row for row in (await db.scalars(select(UserGroup))).all() if row.code
            }
            cards = {
                row.snapshot.get("template_snapshot", {}).get("demo_seed_code"): row
                for row in (await db.scalars(select(SavedIncidentCard))).all()
                if row.snapshot.get("template_snapshot", {}).get("demo_seed_code")
            }
            unit = (await db.scalars(select(ResponseUnit).where(
                ResponseUnit.seed_code == "DEMO_DDS_UNIT_01"
            ))).one()
            for entry in load_sessions():
                existing = await db.scalar(select(TrainingSession.id).where(
                    TrainingSession.title == entry["title"],
                    TrainingSession.instructor_id == instructor.id,
                ))
                if existing is not None:
                    stats["unchanged"] += 1
                    continue
                started = datetime.fromisoformat(entry["started_at"])
                completed = _at(started, 1500)
                people = sorted({case["trainee"] for case in entry["cases"]})
                group = groups[entry["group_code"]]
                session = TrainingSession(
                    title=entry["title"], topic=entry["topic"],
                    mode=TrainingMode.FIXED_SET, duration_minutes=25,
                    workstation_count=len(people), instructor_id=instructor.id,
                    state=TrainingSessionState.COMPLETED,
                    created_at=_at(started, -3600), started_at=started,
                    completed_at=completed, finish_mode="IMMEDIATE",
                    trainees=[users[username] for username in people],
                )
                db.add(session)
                await db.flush()
                training_group = TrainingGroup(
                    training_session_id=session.id,
                    source_user_group_id=group.id,
                    name=group.name, dds_profile="ДДС 101",
                    difficulty="Средняя", queue_mode=QueueMode.INDIVIDUAL_QUEUE,
                )
                db.add(training_group)
                await db.flush()
                runs = {}
                for workstation, username in enumerate(people, 1):
                    trainee = users[username]
                    run = TrainingRun(
                        training_session_id=session.id, trainee_id=trainee.id,
                        dds_profile="ДДС 101", workstation_number=workstation,
                        difficulty="Средняя", queue_mode=QueueMode.INDIVIDUAL_QUEUE,
                        group_id=training_group.id, started_at=started,
                    )
                    db.add(run)
                    runs[username] = run
                await db.flush()
                by_run: dict[int, list[Incident]] = {run.id: [] for run in runs.values()}
                comments: dict[int, list[str]] = {run.id: [] for run in runs.values()}
                for index, case in enumerate(entry["cases"], 1):
                    trainee = users[case["trainee"]]
                    run = runs[case["trainee"]]
                    incident = await _create_case(
                        db, session, run, trainee, cards[case["card"]], unit,
                        case, index, started,
                    )
                    by_run[run.id].append(incident)
                    comments[run.id].append(case["comment"])
                    db.add(InstructorNote(
                        training_run_id=run.id, instructor_id=instructor.id,
                        body=f"{incident.incident_number}: {case['comment']}",
                        created_at=_at(started, case["offset"] + 360),
                    ))
                await db.flush()
                for run in runs.values():
                    result = assess_run(run, by_run[run.id], [], [])
                    for deviation in result.deviations:
                        deviation.decision = "CONFIRMED"
                    result.final_score = result.automatic_score
                    result.score_override = result.automatic_score
                    result.final_comment = " ".join(comments[run.id])
                    result.ai_summary = (
                        f"Обработано карточек: {result.metrics['cards']}; "
                        f"завершено: {result.metrics['completed']}. "
                        + ("Нарушения: " + "; ".join(
                            item.description for item in result.deviations
                        ) if result.deviations else "Отклонений по расчётным правилам нет.")
                    )
                    result.ai_summary_provider = "demo-seed"
                    result.ai_summary_generated_at = completed
                    result.generated_at = completed
                    result.confirmed_at = completed
                    result.confirmed_by = instructor.id
                    db.add(result)
                    await db.flush()
                    db.add(AssessmentAudit(
                        assessment_result_id=result.id, changed_by=instructor.id,
                        changed_at=completed, action="finalize",
                        before={"final_score": None},
                        after={"final_score": result.final_score,
                               "final_comment": result.final_comment},
                        reason="Итог демонстрационного занятия",
                    ))
                stats["created"] += 1
            await db.commit()
    finally:
        await engine.dispose()
    return stats


if __name__ == "__main__":
    print(asyncio.run(seed_demo_history()))
