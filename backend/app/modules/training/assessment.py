"""Итог занятия: воспроизводимый расчёт и аудируемое решение преподавателя."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import (
    DDSResponseStatus,
    Incident,
    IncidentActionType,
    IncidentLifecycleState,
)
from app.modules.response.models import ResponseAssignment, ResponseMessageSender
from app.modules.training.clock import active_seconds
from app.modules.training.models import (
    AssessmentAudit,
    AssessmentDeviation,
    AssessmentResult,
    InstructorNote,
    RunPause,
    SessionPause,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
)
from app.modules.training.router import _ensure_session_owner, _load_session

router = APIRouter(prefix="/api/training", tags=["assessment"])
REACTION_LIMIT_SECONDS = 30


class DecisionRequest(BaseModel):
    decision: Literal["CONFIRMED", "DISMISSED"]
    reason: str = Field(min_length=1, max_length=2000)


class ManualDeviationRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    weight: int = Field(ge=1, le=100)
    incident_id: int | None = None
    critical: bool = False
    reason: str = Field(min_length=1, max_length=2000)


class FinalizeRequest(BaseModel):
    final_score: int | None = Field(default=None, ge=0, le=100)
    final_comment: str = Field(default="", max_length=5000)
    reason: str = Field(min_length=1, max_length=2000)


def _require_reason(reason: str) -> str:
    if not reason.strip():
        raise HTTPException(422, "Укажите причину изменения")
    return reason.strip()


def _owner(incident: Incident) -> int | None:
    return incident.claimed_by_training_run_id or incident.training_run_id


def _deviation(
    incident: Incident | None, kind: str, description: str, weight: int, *, critical: bool = False
) -> AssessmentDeviation:
    return AssessmentDeviation(
        incident_id=incident.id if incident else None,
        kind=kind,
        description=description,
        weight=weight,
        critical=critical,
    )


def assess_run(
    run: TrainingRun, incidents: list[Incident], session_pauses: list, run_pauses: list
) -> AssessmentResult:
    """Снимок правил v1. Учебное время исключает паузы, свободный текст не оценивается."""
    deviations: list[AssessmentDeviation] = []
    reactions: list[float] = []
    completed = refusals = 0
    for incident in incidents:
        prefix = f"{incident.incident_number}: "
        first = incident.primary_status_at
        if incident.delivered_at and first:
            reaction = active_seconds(incident.delivered_at, first, session_pauses, run_pauses)
            reactions.append(reaction)
            if reaction > REACTION_LIMIT_SECONDS:
                deviations.append(
                    _deviation(
                        incident,
                        "SLOW_REACTION",
                        prefix + f"Первичное решение через {round(reaction)} с "
                        f"(норматив {REACTION_LIMIT_SECONDS} с)",
                        5,
                    )
                )
        elif incident.delivered_at:
            deviations.append(
                _deviation(
                    incident,
                    "NO_PRIMARY_STATUS",
                    prefix + "Нет первичного решения",
                    10,
                    critical=True,
                )
            )

        if incident.lifecycle_state == IncidentLifecycleState.FINISHED:
            completed += 1
        else:
            deviations.append(
                _deviation(incident, "UNFINISHED", prefix + "Карточка не завершена", 8)
            )
        if incident.dds_status in (DDSResponseStatus.REJECTED, DDSResponseStatus.WORK_REFUSED):
            refusals += 1
            deviations.append(
                _deviation(
                    incident,
                    "POSSIBLE_REFUSAL",
                    prefix + "Проверьте обоснованность отказа",
                    6,
                    critical=True,
                )
            )

        trainee_actions = [
            action for action in incident.actions if not action.is_system and action.action
        ]
        for action in trainee_actions:
            if (
                action.action in (IncidentActionType.REJECT, IncidentActionType.REFUSE_WORK)
                and not (action.comment or "").strip()
            ):
                deviations.append(
                    _deviation(
                        incident,
                        "MISSING_COMMENT",
                        prefix + "Отказ без обязательного комментария",
                        7,
                    )
                )
        progress_order = {
            IncidentActionType.ACCEPT: 0,
            IncidentActionType.START_RESPONSE: 1,
            IncidentActionType.MARK_ARRIVAL: 2,
            IncidentActionType.START_WORK: 3,
            IncidentActionType.COMPLETE_WORK: 4,
        }
        observed = [
            progress_order[action.action]
            for action in trainee_actions
            if action.action in progress_order
        ]
        if observed != sorted(observed):
            deviations.append(
                _deviation(
                    incident, "EVENT_ORDER", prefix + "Нарушена последовательность действий", 5
                )
            )
        if incident.dds_status in (
            DDSResponseStatus.ACCEPTED,
            DDSResponseStatus.RESPONSE_STARTED,
            DDSResponseStatus.ARRIVED,
            DDSResponseStatus.WORKING,
            DDSResponseStatus.COMPLETED,
        ):
            performed = {action.action for action in trainee_actions}
            required = [IncidentActionType.ACCEPT]
            if incident.dds_status == DDSResponseStatus.COMPLETED:
                required += [
                    IncidentActionType.START_RESPONSE,
                    IncidentActionType.MARK_ARRIVAL,
                    IncidentActionType.START_WORK,
                    IncidentActionType.COMPLETE_WORK,
                ]
            for action_type in required:
                if action_type not in performed:
                    deviations.append(
                        _deviation(
                            incident,
                            "MISSING_ACTION",
                            prefix + f"Пропущено действие {action_type.value}",
                            5,
                        )
                    )

        for assignment in incident.response_assignments:
            messages = sorted(assignment.messages, key=lambda item: (item.created_at, item.id))
            for message in messages:
                if message.sender_type != ResponseMessageSender.RESPONSE_UNIT:
                    continue
                if message.read_at is None:
                    deviations.append(
                        _deviation(
                            incident,
                            "UNREAD_MESSAGE",
                            prefix + "Не прочитано сообщение группы реагирования",
                            4,
                        )
                    )
                elif not any(
                    other.sender_type == ResponseMessageSender.DISPATCHER
                    and other.created_at > message.created_at
                    for other in messages
                ):
                    deviations.append(
                        _deviation(
                            incident,
                            "NO_MESSAGE_REACTION",
                            prefix + "Нет ответа на сообщение группы реагирования",
                            3,
                        )
                    )

    score = max(0, 100 - sum(item.weight for item in deviations))
    metrics = {
        "cards": len(incidents),
        "completed": completed,
        "refusals": refusals,
        "average_reaction_seconds": round(sum(reactions) / len(reactions), 1)
        if reactions
        else None,
        "reaction_violations": sum(item.kind == "SLOW_REACTION" for item in deviations),
        "critical_signals": sum(item.critical for item in deviations),
        "rules_version": 1,
    }
    return AssessmentResult(
        training_run_id=run.id, automatic_score=score, metrics=metrics, deviations=deviations
    )


async def _incidents(database: AsyncSession, session_id: int) -> list[Incident]:
    return list(
        (
            await database.scalars(
                select(Incident)
                .where(Incident.training_session_id == session_id)
                .options(
                    selectinload(Incident.actions),
                    selectinload(Incident.response_assignments).selectinload(
                        ResponseAssignment.messages
                    ),
                )
                .order_by(Incident.id)
            )
        ).all()
    )


async def _results(database: AsyncSession, session: TrainingSession) -> list[AssessmentResult]:
    return list(
        (
            await database.scalars(
                select(AssessmentResult)
                .join(TrainingRun)
                .where(TrainingRun.training_session_id == session.id)
                .options(selectinload(AssessmentResult.deviations))
                .order_by(AssessmentResult.training_run_id)
            )
        ).all()
    )


async def _ensure_results(
    database: AsyncSession, session: TrainingSession
) -> list[AssessmentResult]:
    if session.state != TrainingSessionState.COMPLETED:
        raise HTTPException(409, "Разбор доступен после завершения занятия")
    results = await _results(database, session)
    existing = {item.training_run_id for item in results}
    missing = [run for run in session.runs if run.id not in existing]
    if missing:
        incidents = await _incidents(database, session.id)
        pauses = list(
            (
                await database.scalars(
                    select(SessionPause).where(SessionPause.training_session_id == session.id)
                )
            ).all()
        )
        run_pauses = list(
            (
                await database.scalars(
                    select(RunPause).where(
                        RunPause.training_run_id.in_([run.id for run in missing])
                    )
                )
            ).all()
        )
        for run in missing:
            database.add(
                assess_run(
                    run,
                    [incident for incident in incidents if _owner(incident) == run.id],
                    pauses,
                    [pause for pause in run_pauses if pause.training_run_id == run.id],
                )
            )
        await database.commit()
        results = await _results(database, session)
    return results


def _score(result: AssessmentResult) -> int:
    return max(
        0,
        min(
            100,
            100 - sum(item.weight for item in result.deviations if item.decision != "DISMISSED"),
        ),
    )


def _audit(
    result: AssessmentResult, user: User, action: str, before: dict, after: dict, reason: str
) -> AssessmentAudit:
    return AssessmentAudit(
        assessment_result_id=result.id,
        changed_by=user.id,
        action=action,
        before=before,
        after=after,
        reason=reason,
    )


def _result_read(
    result: AssessmentResult, notes: list[InstructorNote], *, public: bool = False
) -> dict:
    data = {
        "run_id": result.training_run_id,
        "automatic_score": result.automatic_score,
        "final_score": result.final_score,
        "confirmed_at": result.confirmed_at,
        "final_comment": result.final_comment,
        "metrics": result.metrics,
        "deviations": [
            {
                "id": item.id,
                "incident_id": item.incident_id,
                "kind": item.kind,
                "description": item.description,
                "weight": item.weight,
                "critical": item.critical,
                "decision": item.decision,
                "is_manual": item.is_manual,
            }
            for item in result.deviations
        ],
    }
    if public:
        data.pop("automatic_score")
        data["deviations"] = [
            item for item in data["deviations"] if item["decision"] == "CONFIRMED"
        ]
        data["metrics"] = {
            **result.metrics,
            "reaction_violations": sum(
                item["kind"] == "SLOW_REACTION" for item in data["deviations"]
            ),
            "critical_signals": sum(item["critical"] for item in data["deviations"]),
        }
    else:
        data["notes"] = [{"body": note.body, "created_at": note.created_at} for note in notes]
        data["calculated_score"] = _score(result)
    return data


async def _notes(database: AsyncSession, run_ids: list[int]) -> list[InstructorNote]:
    if not run_ids:
        return []
    return list(
        (
            await database.scalars(
                select(InstructorNote)
                .where(InstructorNote.training_run_id.in_(run_ids))
                .order_by(InstructorNote.id)
            )
        ).all()
    )


@router.get("/sessions/{session_id}/assessment")
async def class_assessment(
    session_id: int,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session = await _load_session(database, session_id, for_update=True)
    _ensure_session_owner(session, user)
    results = await _ensure_results(database, session)
    notes = await _notes(database, [run.id for run in session.runs])
    incidents = await _incidents(database, session.id)
    incident_by_id = {incident.id: incident for incident in incidents}
    rows = []
    for run in sorted(session.runs, key=lambda item: (item.workstation_number or 999, item.id)):
        result = next(item for item in results if item.training_run_id == run.id)
        problem_ids = {item.incident_id for item in result.deviations if item.incident_id}
        problem_cards = []
        for incident_id in sorted(problem_ids):
            incident = incident_by_id.get(incident_id)
            if incident is None:
                continue
            timeline = [{"at": incident.delivered_at, "event": "Карточка поступила"}]
            timeline.extend(
                {"at": action.created_at, "event": action.status, "comment": action.comment}
                for action in incident.actions
            )
            if incident.finished_at:
                timeline.append({"at": incident.finished_at, "event": "Карточка завершена"})
            problem_cards.append(
                {
                    "id": incident.id,
                    "incident_number": incident.incident_number,
                    "timeline": timeline,
                }
            )
        rows.append(
            {
                **_result_read(result, [note for note in notes if note.training_run_id == run.id]),
                "trainee_name": run.trainee.full_name,
                "workstation_number": run.workstation_number,
                "dds_profile": run.dds_profile,
                "difficulty": run.difficulty,
                "problem_cards": problem_cards,
            }
        )
    return {
        "session_id": session.id,
        "title": session.title,
        "completed_at": session.completed_at,
        "summary": {
            "trainees": len(session.runs),
            "cards": len(incidents),
            "completed": sum(
                item.lifecycle_state == IncidentLifecycleState.FINISHED for item in incidents
            ),
            "refusals": sum(
                item.dds_status in (DDSResponseStatus.REJECTED, DDSResponseStatus.WORK_REFUSED)
                for item in incidents
            ),
            "reaction_violations": sum(row["metrics"]["reaction_violations"] for row in rows),
            "critical_signals": sum(row["metrics"]["critical_signals"] for row in rows),
        },
        "runs": rows,
    }


async def _editable_result(
    database: AsyncSession, session_id: int, run_id: int, user: User
) -> AssessmentResult:
    session = await _load_session(database, session_id, for_update=True)
    _ensure_session_owner(session, user)
    if run_id not in {run.id for run in session.runs}:
        raise HTTPException(404, "Участник не найден")
    await _ensure_results(database, session)
    result = await database.scalar(
        select(AssessmentResult)
        .where(AssessmentResult.training_run_id == run_id)
        .options(selectinload(AssessmentResult.deviations))
        .with_for_update(of=AssessmentResult)
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise HTTPException(404, "Результат не найден")
    return result


@router.post("/sessions/{session_id}/runs/{run_id}/deviations/{deviation_id}/decision")
async def decide_deviation(
    session_id: int,
    run_id: int,
    deviation_id: int,
    payload: DecisionRequest,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    reason = _require_reason(payload.reason)
    result = await _editable_result(database, session_id, run_id, user)
    item = next((item for item in result.deviations if item.id == deviation_id), None)
    if item is None:
        raise HTTPException(404, "Отклонение не найдено")
    before = {"decision": item.decision, "final_score": result.final_score}
    item.decision = payload.decision
    if result.confirmed_at:
        result.final_score = (
            result.score_override if result.score_override is not None else _score(result)
        )
    database.add(
        _audit(
            result,
            user,
            "deviation_decision",
            before,
            {"decision": item.decision, "final_score": result.final_score, "deviation_id": item.id},
            reason,
        )
    )
    await database.commit()
    return {
        "decision": item.decision,
        "calculated_score": _score(result),
        "final_score": result.final_score,
    }


@router.post("/sessions/{session_id}/runs/{run_id}/deviations", status_code=201)
async def add_deviation(
    session_id: int,
    run_id: int,
    payload: ManualDeviationRequest,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    reason = _require_reason(payload.reason)
    result = await _editable_result(database, session_id, run_id, user)
    before = {"final_score": result.final_score, "deviation_count": len(result.deviations)}
    if payload.incident_id is not None:
        incident = await database.scalar(
            select(Incident).where(
                Incident.id == payload.incident_id, Incident.training_session_id == session_id
            )
        )
        if incident is None or _owner(incident) != run_id:
            raise HTTPException(422, "Карточка не принадлежит участнику")
    item = AssessmentDeviation(
        incident_id=payload.incident_id,
        kind="INSTRUCTOR_NOTE",
        description=payload.description.strip(),
        weight=payload.weight,
        critical=payload.critical,
        decision="CONFIRMED",
        is_manual=True,
    )
    result.deviations.append(item)
    await database.flush()
    if result.confirmed_at:
        result.final_score = (
            result.score_override if result.score_override is not None else _score(result)
        )
    database.add(
        _audit(
            result,
            user,
            "add_deviation",
            before,
            {
                "deviation_id": item.id,
                "weight": item.weight,
                "final_score": result.final_score,
                "deviation_count": len(result.deviations),
            },
            reason,
        )
    )
    await database.commit()
    return {"id": item.id, "calculated_score": _score(result), "final_score": result.final_score}


@router.post("/sessions/{session_id}/runs/{run_id}/finalize")
async def finalize_result(
    session_id: int,
    run_id: int,
    payload: FinalizeRequest,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    reason = _require_reason(payload.reason)
    result = await _editable_result(database, session_id, run_id, user)
    if any(item.decision == "PENDING" for item in result.deviations):
        raise HTTPException(409, "Проверьте все найденные отклонения")
    before = {
        "final_score": result.final_score,
        "final_comment": result.final_comment,
        "confirmed_at": result.confirmed_at.isoformat() if result.confirmed_at else None,
    }
    result.score_override = payload.final_score
    result.final_score = payload.final_score if payload.final_score is not None else _score(result)
    result.final_comment = payload.final_comment.strip()
    result.confirmed_at = datetime.now(UTC)
    result.confirmed_by = user.id
    database.add(
        _audit(
            result,
            user,
            "finalize",
            before,
            {
                "final_score": result.final_score,
                "final_comment": result.final_comment,
                "confirmed_at": result.confirmed_at.isoformat(),
            },
            reason,
        )
    )
    await database.commit()
    return {"final_score": result.final_score, "confirmed_at": result.confirmed_at}


@router.get("/sessions/{session_id}/runs/{run_id}/assessment/audit")
async def result_audit(
    session_id: int,
    run_id: int,
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    result = await _editable_result(database, session_id, run_id, user)
    rows = (
        await database.scalars(
            select(AssessmentAudit)
            .where(AssessmentAudit.assessment_result_id == result.id)
            .order_by(AssessmentAudit.id)
        )
    ).all()
    return [
        {
            "id": item.id,
            "changed_by": item.changed_by,
            "changed_at": item.changed_at,
            "action": item.action,
            "before": item.before,
            "after": item.after,
            "reason": item.reason,
        }
        for item in rows
    ]


@router.get("/my/results")
async def my_results(
    user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    if user.role != UserRole.TRAINEE:
        raise HTTPException(403, "История доступна обучаемому")
    rows = (
        await database.execute(
            select(AssessmentResult, TrainingRun, TrainingSession)
            .join(TrainingRun, AssessmentResult.training_run_id == TrainingRun.id)
            .join(TrainingSession, TrainingRun.training_session_id == TrainingSession.id)
            .where(
                TrainingRun.trainee_id == user.id,
                TrainingSession.state == TrainingSessionState.COMPLETED,
                AssessmentResult.confirmed_at.is_not(None),
            )
            .options(selectinload(AssessmentResult.deviations))
            .order_by(TrainingSession.completed_at.desc())
        )
    ).all()
    return [
        {
            "session_id": session.id,
            "date": session.completed_at,
            "title": session.title,
            "dds_profile": run.dds_profile,
            "difficulty": run.difficulty,
            "cards": result.metrics["cards"],
            "result": _result_read(result, [], public=True),
        }
        for result, run, session in rows
    ]
