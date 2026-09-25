"""Deterministic preparation of instructor-only scenario instances."""

from __future__ import annotations

import random
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.models import User, UserRole
from app.modules.incident_classifier.models import (
    DispatchService,
    IncidentClassifierRule,
    IncidentRuleFeature,
    IncidentRuleService,
)
from app.modules.object_registry.models import CityObject, ObjectTag, ObjectType
from app.modules.object_registry.queries import descendant_type_ids
from app.modules.scenario_library.instance_models import (
    ScenarioInstance,
    ScenarioInstanceEvent,
    ScenarioRuntimeEvent,
)
from app.modules.scenario_library.router import get_template, readiness_errors, require_editor
from app.modules.scenario_library.runtime import incident_snapshot
from app.modules.scenario_library.variants import card_seeds, object_order, variant_facts
from app.modules.training.delivery import _editable, _invalidate_readiness, _new_item
from app.modules.training.models import (
    QueueMode,
    ScenarioQueueItem,
    TrainingSession,
    TrainingSessionState,
)
from app.modules.training.router import _ensure_session_owner, _load_session
from app.services.text_generation.renderer import (
    TextGenerationRequest,
    TextGenerationTask,
    renderer_for_database,
)

template_router = APIRouter(prefix="/api/scenario-templates", tags=["scenario-instances"])
instance_router = APIRouter(prefix="/api/scenario-instances", tags=["scenario-instances"])
session_router = APIRouter(prefix="/api/training/sessions", tags=["scenario-instances"])


class GenerationInput(BaseModel):
    object_id: int | None = None
    object_query: str = Field(default="", max_length=200)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    seed: int = Field(default=0, ge=0, le=2147483647)
    variant_mode: Literal["MANUAL", "RANDOM"] = "MANUAL"
    training_session_id: int | None = None


class BatchGenerationInput(BaseModel):
    count: int = Field(ge=1, le=50)
    seed: int = Field(default=0, ge=0, le=2147483647)
    training_session_id: int = Field(gt=0)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    different_objects: bool = True


class MaterializeInput(BaseModel):
    training_run_id: int | None = Field(default=None, gt=0)
    training_group_id: int | None = Field(default=None, gt=0)


@instance_router.post("/{instance_id}/materialize")
async def materialize(
    instance_id: int,
    data: MaterializeInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    """Prepare an immutable instance in the canonical queue; delivery creates Incident."""
    await read_instance(instance_id, user, database)
    instance = await database.get(ScenarioInstance, instance_id)
    if instance.training_session_id is None:
        raise HTTPException(409, "Сначала привяжите экземпляр к занятию")
    session = await _load_session(database, instance.training_session_id, for_update=True)
    _ensure_session_owner(session, user)
    existing = await database.scalar(
        select(ScenarioQueueItem).where(ScenarioQueueItem.scenario_instance_id == instance_id)
    )
    if existing is not None:
        return {"queue_item_id": existing.id, "incident_id": existing.incident_id}
    _editable(session, user)
    if instance.status != "CONFIRMED":
        raise HTTPException(409, "Экземпляр не подтверждён")
    if (data.training_run_id is None) == (data.training_group_id is None):
        raise HTTPException(422, "Укажите один АРМ или одну общую группу")
    if data.training_run_id is not None and data.training_run_id not in {
        run.id for run in session.runs if run.queue_mode == QueueMode.INDIVIDUAL_QUEUE
    }:
        raise HTTPException(422, "АРМ не принадлежит индивидуальной очереди занятия")
    if data.training_group_id is not None and data.training_group_id not in {
        group.id for group in session.groups if group.queue_mode == QueueMode.SHARED_QUEUE
    }:
        raise HTTPException(422, "Группа не принадлежит общей очереди занятия")
    item = _new_item(
        session,
        data.training_run_id,
        instance.name[:200],
        incident_snapshot(instance),
        group_id=data.training_group_id,
    )
    item.scenario_instance_id = instance.id
    _invalidate_readiness(session)
    await database.commit()
    return {"queue_item_id": item.id, "incident_id": None}


@instance_router.get("/{instance_id}/materialization")
async def read_materialization(
    instance_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    await read_instance(instance_id, user, database)
    item = await database.scalar(
        select(ScenarioQueueItem).where(ScenarioQueueItem.scenario_instance_id == instance_id)
    )
    events = []
    if item and item.incident_id:
        rows = (
            await database.scalars(
                select(ScenarioRuntimeEvent)
                .where(ScenarioRuntimeEvent.incident_id == item.incident_id)
                .order_by(ScenarioRuntimeEvent.offset_seconds, ScenarioRuntimeEvent.id)
            )
        ).all()
        events = [
            {
                "scenario_instance_event_id": row.scenario_instance_event_id,
                "event_type": row.event_type,
                "offset_seconds": row.offset_seconds,
                "status": row.status,
                "released_at": row.released_at,
            }
            for row in rows
        ]
    return {
        "queue_item_id": item.id if item else None,
        "incident_id": item.incident_id if item else None,
        "delivery_state": item.delivery_state if item else None,
        "runtime_events": events,
    }


def _event_dict(row, services: list[dict] | None = None) -> dict:
    if isinstance(row, ScenarioInstanceEvent):
        payload = row.payload_snapshot
    else:
        target = next(
            (
                service
                for service in services or []
                if service["service_id"] == row.target_service_id
            ),
            None,
        )
        payload = {
            "title": row.title,
            "description": row.description,
            "source_type": row.source_type,
            "target_service_id": row.target_service_id,
            "target_service_name": target["official_name"] if target else None,
            "target_service_source": target["source_reference"] if target else None,
        }
    result = {
        "sequence_number": row.sequence_number,
        "offset_seconds": row.offset_seconds,
        "event_type": row.event_type,
        "title": row.title,
        "description": row.description,
        "source_type": row.source_type,
        "payload_snapshot": payload,
    }
    if isinstance(row, ScenarioInstanceEvent):
        result["payload_snapshot"] = row.payload_snapshot
        result["render"] = row.payload_snapshot.get("render")
    return result


def _initial_request(content: dict) -> TextGenerationRequest:
    initial = content["initial_state_snapshot"]
    return TextGenerationRequest(
        task=TextGenerationTask.INCIDENT_REPORT,
        facts={
            "description": initial["description"],
            "caller_text": initial.get("caller_text"),
            "title": initial["title"],
            "incident_type": content["classifier_snapshot"]["final_incident_type"],
            "object_name": content["object_snapshot"]["name"],
            "address": content["object_snapshot"].get("address"),
            "variant_facts": initial.get("variant_facts", {}),
        },
    )


def _response_request(event: dict) -> TextGenerationRequest:
    return TextGenerationRequest(
        task=TextGenerationTask.RESPONSE_MESSAGE,
        facts={
            "title": event["title"],
            "description": event["description"],
            "source_type": event["source_type"],
        },
    )


async def _render_content(content: dict, database: AsyncSession) -> None:
    renderer = await renderer_for_database(database)
    rendered = [await renderer.render(_initial_request(content))]
    content["initial_state_snapshot"]["render"] = rendered[0]
    for event in content["events"]:
        if event["event_type"] == "RESPONSE_MESSAGE":
            result = await renderer.render(_response_request(event))
            event["payload_snapshot"]["render"] = result
            rendered.append(result)
    await _record_usage(database, rendered)


async def _record_usage(database: AsyncSession, rendered: list[dict]) -> None:
    """Count committed render operations for the existing admin usage view."""
    from datetime import UTC, datetime

    statement = text(
        "INSERT INTO ai_usage_daily "
        "(day, requests, input_tokens, output_tokens, fallbacks, errors) "
        "VALUES (:day, :requests, :input_tokens, :output_tokens, :fallbacks, :errors) "
        "ON CONFLICT (day) DO UPDATE SET "
        "requests = ai_usage_daily.requests + excluded.requests, "
        "input_tokens = ai_usage_daily.input_tokens + excluded.input_tokens, "
        "output_tokens = ai_usage_daily.output_tokens + excluded.output_tokens, "
        "fallbacks = ai_usage_daily.fallbacks + excluded.fallbacks, "
        "errors = ai_usage_daily.errors + excluded.errors"
    ).bindparams(
        day=datetime.now(UTC).date(),
        requests=len(rendered),
        input_tokens=sum(item.get("input_tokens") or 0 for item in rendered),
        output_tokens=sum(item.get("output_tokens") or 0 for item in rendered),
        fallbacks=sum(bool(item.get("fallback_used")) for item in rendered),
        errors=sum(bool(item.get("provider_error")) for item in rendered),
    )
    await database.execute(statement)


async def _matching_objects(database: AsyncSession, template) -> list:
    rule = template.object_rule
    if rule is None:
        return []
    type_code = await database.scalar(
        select(ObjectType.code).where(ObjectType.id == rule.object_type_id)
    )
    if type_code is None:
        return []
    query = select(CityObject.id, CityObject.name, CityObject.address, CityObject.district).where(
        CityObject.object_type_id.in_(descendant_type_ids(type_code))
    )
    if rule.selection_mode == "OBJECT_BOUND":
        query = query.where(CityObject.id == rule.specific_object_id)
    for item in rule.required_tags:
        query = query.where(
            CityObject.id.in_(select(ObjectTag.object_id).where(ObjectTag.tag == item.tag))
        )
    return (await database.execute(query.order_by(CityObject.id))).all()


async def _build(
    database: AsyncSession, template_id: int, data: GenerationInput, user: User
) -> dict:
    template = await get_template(database, template_id)
    if template.status != "READY":
        raise HTTPException(status_code=409, detail="Генерация доступна только для READY-шаблона")
    errors = await readiness_errors(database, template)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    objects = await _matching_objects(database, template)
    if not objects:
        raise HTTPException(status_code=422, detail="Нет подходящих объектов")
    rule = template.object_rule
    if rule.selection_mode == "OBJECT_BOUND":
        selected_row = objects[0]
        if data.object_id is not None and data.object_id != selected_row.id:
            raise HTTPException(status_code=422, detail="Шаблон привязан к другому объекту")
    elif data.object_id is not None:
        selected_row = next((item for item in objects if item.id == data.object_id), None)
        if selected_row is None:
            raise HTTPException(status_code=422, detail="Объект не соответствует правилу шаблона")
    elif data.variant_mode == "RANDOM":
        selected_row = objects[random.Random(data.seed).randrange(len(objects))]
    else:
        selected_row = None

    selected = None
    if selected_row is not None:
        selected = (
            await database.scalars(
                select(CityObject)
                .where(CityObject.id == selected_row.id)
                .options(
                    selectinload(CityObject.object_type),
                    selectinload(CityObject.attributes),
                    selectinload(CityObject.tags),
                )
            )
        ).one()

    classifier = await database.get(IncidentClassifierRule, template.classifier_rule_id)
    if classifier is None:
        raise HTTPException(status_code=422, detail="Правило SRC-006 отсутствует")
    feature_links = (
        await database.scalars(
            select(IncidentRuleFeature)
            .where(IncidentRuleFeature.rule_id == classifier.id)
            .options(selectinload(IncidentRuleFeature.feature))
        )
    ).all()
    classifier_services = set(
        (
            await database.scalars(
                select(IncidentRuleService.service_id).where(
                    IncidentRuleService.rule_id == classifier.id
                )
            )
        ).all()
    )
    derived_services = (
        await database.scalars(
            select(DispatchService)
            .where(DispatchService.id.in_(classifier_services))
            .order_by(DispatchService.id)
        )
    ).all()
    classifier_snapshot = {
        "rule_id": classifier.id,
        "source_code": classifier.source_code,
        "source_reference": classifier.source_reference,
        "incident_group": classifier.incident_group,
        "final_incident_type": classifier.final_incident_type,
        "ekp35_type": classifier.ekp35_type,
        "features": [
            {
                "id": link.feature.id,
                "name": link.feature.name,
                "level": link.feature.level,
                "source_column": link.feature.source_column,
                "source_value": link.feature.source_value,
            }
            for link in feature_links
        ],
        "derived_service_ids": sorted(classifier_services),
        "derived_services": [
            {
                "id": service.id,
                "official_name": service.official_name,
                "source_reference": service.source_reference,
            }
            for service in derived_services
        ],
    }
    services = []
    for link in template.services:
        service = await database.get(DispatchService, link.service_id)
        if service is None or (
            link.source == "CLASSIFIER" and link.service_id not in classifier_services
        ):
            raise HTTPException(status_code=422, detail=f"Служба {link.service_id} не подтверждена")
        services.append(
            {
                "service_id": service.id,
                "official_name": service.official_name,
                "organization": service.organization,
                "service_level": service.service_level,
                "source_reference": service.source_reference,
                "selection_reason": link.source,
            }
        )
    for action in template.expected_actions:
        if (
            action.expected_service_id is not None
            and await database.get(DispatchService, action.expected_service_id) is None
        ):
            raise HTTPException(status_code=422, detail="Служба ожидаемого действия отсутствует")
    object_snapshot = (
        None
        if selected is None
        else {
            "id": selected.id,
            "source": selected.source,
            "external_id": selected.external_id,
            "name": selected.name,
            "object_type_id": selected.object_type_id,
            "object_type_code": selected.object_type.code,
            "object_type_name": selected.object_type.name,
            "address": selected.address,
            "district": selected.district,
            "administrative_area": selected.administrative_area,
            "latitude": str(selected.latitude) if selected.latitude is not None else None,
            "longitude": str(selected.longitude) if selected.longitude is not None else None,
            "tags": sorted(tag.tag for tag in selected.tags),
            "attributes": [
                {"code": attr.attribute_code, "value": attr.value, "value_type": attr.value_type}
                for attr in sorted(selected.attributes, key=lambda x: x.attribute_code)
            ],
        }
    )
    if data.training_session_id is not None:
        await _session(database, data.training_session_id, user)
    variation = variant_facts(template.seed_code, data.seed)
    initial_description = template.initial_description
    if variation:
        initial_description = (
            f"{variation['observation']} на {variation['floor']} этаже, "
            f"{variation['room']}; {variation['casualties']}."
        )
    return {
        "scenario_template_id": template.id,
        "training_session_id": data.training_session_id,
        "name": f"{template.name} — {selected.name}" if selected else template.name,
        "difficulty": data.difficulty or template.difficulty,
        "generation_seed": data.seed,
        "classifier_snapshot": classifier_snapshot,
        "object_snapshot": object_snapshot,
        "matching_objects": [
            {"id": obj.id, "name": obj.name, "address": obj.address, "district": obj.district}
            for obj in (
                [
                    item
                    for item in objects
                    if data.object_query.strip().casefold()
                    in f"{item.name} {item.address or ''} {item.district or ''}".casefold()
                ]
                if data.object_query.strip()
                else objects
            )[:100]
        ],
        "matching_object_count": len(objects),
        "service_snapshot": services,
        "initial_state_snapshot": {
            "title": template.initial_title,
            "description": initial_description,
            "caller_text": template.initial_caller_text,
            "variant_facts": variation,
        },
        "events": [_event_dict(event, services) for event in template.events],
        "expected_actions_snapshot": [
            {
                "expected_action_type": a.expected_action_type,
                "target_status": a.target_status,
                "expected_service_id": a.expected_service_id,
                "deadline_seconds": a.deadline_seconds,
                "is_critical": a.is_critical,
                "description": a.description,
            }
            for a in template.expected_actions
        ],
        "assessment_criteria_snapshot": [
            {
                "name": c.name,
                "description": c.description,
                "weight": c.weight,
                "is_critical": c.is_critical,
            }
            for c in template.criteria
        ],
        "template_snapshot": {
            "id": template.id,
            "version": template.version,
            "name": template.name,
            "description": template.description,
            "object_rule": {
                "selection_mode": rule.selection_mode,
                "object_type_id": rule.object_type_id,
                "required_tags": [tag.tag for tag in rule.required_tags],
            },
        },
        "warnings": [],
    }


async def _session(database: AsyncSession, session_id: int, user: User) -> TrainingSession:
    session = await database.get(TrainingSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    if user.role != UserRole.ADMIN and session.instructor_id != user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к занятию")
    if session.state not in (TrainingSessionState.DRAFT, TrainingSessionState.READY):
        raise HTTPException(status_code=409, detail="Занятие уже началось или завершено")
    return session


def _serialize(row: ScenarioInstance) -> dict:
    return {
        "id": row.id,
        "scenario_template_id": row.scenario_template_id,
        "training_session_id": row.training_session_id,
        "created_by_user_id": row.created_by_user_id,
        "name": row.name,
        "difficulty": row.difficulty,
        "generation_seed": row.generation_seed,
        "status": row.status,
        "classifier_snapshot": row.classifier_snapshot,
        "object_snapshot": row.object_snapshot,
        "service_snapshot": row.service_snapshot,
        "initial_state_snapshot": row.initial_state_snapshot,
        "expected_actions_snapshot": row.expected_actions_snapshot,
        "assessment_criteria_snapshot": row.assessment_criteria_snapshot,
        "template_snapshot": row.template_snapshot,
        "created_at": row.created_at,
        "events": [{**_event_dict(e, row.service_snapshot), "id": e.id} for e in row.events],
    }


@template_router.post("/{template_id}/generate-preview")
async def preview(
    template_id: int,
    data: GenerationInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    return await _build(database, template_id, data, user)


@template_router.post("/{template_id}/instances", status_code=201)
async def generate(
    template_id: int,
    data: GenerationInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    content = await _build(database, template_id, data, user)
    if content["object_snapshot"] is None:
        raise HTTPException(status_code=422, detail="Выберите подходящий объект")
    await _render_content(content, database)
    row = _instance_from_content(template_id, content, user)
    database.add(row)
    await database.commit()
    return await read_instance(row.id, user, database)


def _instance_from_content(template_id: int, content: dict, user: User) -> ScenarioInstance:
    return ScenarioInstance(
        scenario_template_id=template_id,
        training_session_id=content["training_session_id"],
        created_by_user_id=user.id,
        name=content["name"],
        difficulty=content["difficulty"],
        generation_seed=content["generation_seed"],
        status="DRAFT",
        classifier_snapshot=content["classifier_snapshot"],
        object_snapshot=content["object_snapshot"],
        service_snapshot=content["service_snapshot"],
        initial_state_snapshot=content["initial_state_snapshot"],
        expected_actions_snapshot=content["expected_actions_snapshot"],
        assessment_criteria_snapshot=content["assessment_criteria_snapshot"],
        template_snapshot=content["template_snapshot"],
        events=[ScenarioInstanceEvent(**event) for event in content["events"]],
    )


@template_router.post("/{template_id}/batch", status_code=201)
async def generate_batch(
    template_id: int,
    data: BatchGenerationInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    """Prepare a set of distinct, reviewable drafts in one transaction."""
    await _session(database, data.training_session_id, user)
    template = await get_template(database, template_id)
    objects = await _matching_objects(database, template)
    if not objects:
        raise HTTPException(status_code=422, detail="Нет подходящих объектов")
    if template.seed_code != "DEMO_EDUCATION_FIRE_001" and len(objects) < data.count:
        raise HTTPException(422, "Для этого сценария недостаточно разных объектов")
    ordered_ids = object_order([item.id for item in objects], data.seed)
    rows = []
    seen = set()
    seeds = card_seeds(data.seed, data.count * 10)
    for index in range(data.count):
        object_id = ordered_ids[index % len(ordered_ids)] if data.different_objects else None
        for candidate in seeds[index * 10 : (index + 1) * 10]:
            content = await _build(
                database,
                template_id,
                GenerationInput(
                    object_id=object_id,
                    difficulty=data.difficulty,
                    seed=candidate,
                    variant_mode="RANDOM",
                    training_session_id=data.training_session_id,
                ),
                user,
            )
            key = (
                content["object_snapshot"]["id"],
                tuple(sorted(content["initial_state_snapshot"]["variant_facts"].items())),
            )
            if key not in seen:
                seen.add(key)
                break
        else:
            raise HTTPException(422, "Не удалось сформировать достаточно разных карточек")
        await _render_content(content, database)
        row = _instance_from_content(template_id, content, user)
        database.add(row)
        rows.append(row)
    await database.commit()
    return [await read_instance(row.id, user, database) for row in rows]


class ManualTextInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


async def _editable_instance(instance_id: int, user: User, database: AsyncSession):
    await read_instance(instance_id, user, database)
    row = (
        await database.scalars(
            select(ScenarioInstance)
            .where(ScenarioInstance.id == instance_id)
            .options(selectinload(ScenarioInstance.events))
        )
    ).one()
    if row.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Подтверждённый экземпляр неизменяем")
    return row


@instance_router.post("/{instance_id}/rerender-initial-message")
async def rerender_initial(
    instance_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    row = await _editable_instance(instance_id, user, database)
    content = {
        "initial_state_snapshot": row.initial_state_snapshot,
        "classifier_snapshot": row.classifier_snapshot,
        "object_snapshot": row.object_snapshot,
    }
    snapshot = dict(row.initial_state_snapshot)
    snapshot["render"] = await (await renderer_for_database(database)).render(
        _initial_request(content)
    )
    await _record_usage(database, [snapshot["render"]])
    row.initial_state_snapshot = snapshot
    await database.commit()
    return await read_instance(instance_id, user, database)


@instance_router.post("/{instance_id}/regenerate-card")
async def regenerate_card(
    instance_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    """Replace draft facts and prepared texts, leaving confirmed snapshots untouched."""
    row = await _editable_instance(instance_id, user, database)
    original = (
        row.object_snapshot["id"],
        row.initial_state_snapshot.get("variant_facts", {}),
    )
    for attempt in range(1, 21):
        seed = (row.generation_seed + attempt) % 2_147_483_648
        content = await _build(
            database,
            row.scenario_template_id,
            GenerationInput(
                seed=seed,
                variant_mode="RANDOM",
                difficulty=row.difficulty,
                training_session_id=row.training_session_id,
            ),
            user,
        )
        changed = (
            content["object_snapshot"]["id"],
            content["initial_state_snapshot"]["variant_facts"],
        )
        if changed != original:
            break
    else:
        raise HTTPException(422, "Другой вариант этого сценария недоступен")
    await _render_content(content, database)
    row.name = content["name"]
    row.generation_seed = seed
    row.object_snapshot = content["object_snapshot"]
    row.classifier_snapshot = content["classifier_snapshot"]
    row.service_snapshot = content["service_snapshot"]
    row.initial_state_snapshot = content["initial_state_snapshot"]
    row.expected_actions_snapshot = content["expected_actions_snapshot"]
    row.assessment_criteria_snapshot = content["assessment_criteria_snapshot"]
    row.template_snapshot = content["template_snapshot"]
    row.events = [ScenarioInstanceEvent(**event) for event in content["events"]]
    await database.commit()
    return await read_instance(instance_id, user, database)


@instance_router.delete("/{instance_id}", status_code=204)
async def exclude_instance(
    instance_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> None:
    row = await _editable_instance(instance_id, user, database)
    if row.training_session_id is not None:
        await _session(database, row.training_session_id, user)
    await database.delete(row)
    await database.commit()


@instance_router.patch("/{instance_id}/initial-message")
async def edit_initial(
    instance_id: int,
    data: ManualTextInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    row = await _editable_instance(instance_id, user, database)
    snapshot = dict(row.initial_state_snapshot)
    render = dict(snapshot.get("render") or {})
    render.update(rendered_text=data.text.strip(), render_origin="MANUAL")
    snapshot["render"] = render
    row.initial_state_snapshot = snapshot
    await database.commit()
    return await read_instance(instance_id, user, database)


async def _event_for_edit(instance_id: int, event_id: int, user: User, database: AsyncSession):
    row = await _editable_instance(instance_id, user, database)
    event = next((item for item in row.events if item.id == event_id), None)
    if event is None or event.event_type != "RESPONSE_MESSAGE":
        raise HTTPException(status_code=404, detail="Сообщение службы не найдено")
    return event


@instance_router.post("/{instance_id}/events/{event_id}/rerender")
async def rerender_event(
    instance_id: int,
    event_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    event = await _event_for_edit(instance_id, event_id, user, database)
    snapshot = dict(event.payload_snapshot)
    snapshot["render"] = await (await renderer_for_database(database)).render(
        _response_request(_event_dict(event))
    )
    await _record_usage(database, [snapshot["render"]])
    event.payload_snapshot = snapshot
    await database.commit()
    return await read_instance(instance_id, user, database)


@instance_router.patch("/{instance_id}/events/{event_id}/message")
async def edit_event(
    instance_id: int,
    event_id: int,
    data: ManualTextInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    event = await _event_for_edit(instance_id, event_id, user, database)
    snapshot = dict(event.payload_snapshot)
    render = dict(snapshot.get("render") or {})
    render.update(rendered_text=data.text.strip(), render_origin="MANUAL")
    snapshot["render"] = render
    event.payload_snapshot = snapshot
    await database.commit()
    return await read_instance(instance_id, user, database)


@instance_router.post("/{instance_id}/confirm")
async def confirm_instance(
    instance_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    row = await _editable_instance(instance_id, user, database)
    if not row.initial_state_snapshot.get("render", {}).get("rendered_text") or any(
        event.event_type == "RESPONSE_MESSAGE"
        and not event.payload_snapshot.get("render", {}).get("rendered_text")
        for event in row.events
    ):
        raise HTTPException(status_code=409, detail="Сначала подготовьте все тексты")
    row.status = "CONFIRMED"
    await database.commit()
    return await read_instance(instance_id, user, database)


@instance_router.get("")
async def list_instances(
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    query = (
        select(ScenarioInstance)
        .where(ScenarioInstance.status == "DRAFT")
        .options(selectinload(ScenarioInstance.events))
    )
    if user.role != UserRole.ADMIN:
        query = query.where(ScenarioInstance.created_by_user_id == user.id)
    rows = (
        await database.scalars(
            query.order_by(ScenarioInstance.created_at.desc(), ScenarioInstance.id.desc()).limit(
                100
            )
        )
    ).all()
    return [_serialize(row) for row in rows]


@instance_router.get("/{instance_id}")
async def read_instance(
    instance_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    row = (
        await database.scalars(
            select(ScenarioInstance)
            .where(ScenarioInstance.id == instance_id)
            .options(selectinload(ScenarioInstance.events))
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Экземпляр не найден")
    if user.role != UserRole.ADMIN and row.created_by_user_id != user.id:
        if row.training_session_id is None:
            raise HTTPException(status_code=403, detail="Нет доступа к экземпляру")
        session = await database.get(TrainingSession, row.training_session_id)
        if session is None or session.instructor_id != user.id:
            raise HTTPException(status_code=403, detail="Нет доступа к экземпляру")
    return _serialize(row)


@instance_router.post("/{instance_id}/attach")
async def attach(
    instance_id: int,
    data: dict,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    session_id = data.get("training_session_id")
    if not isinstance(session_id, int):
        raise HTTPException(status_code=422, detail="Укажите training_session_id")
    await _session(database, session_id, user)
    await read_instance(instance_id, user, database)
    row = await database.get(ScenarioInstance, instance_id)
    if row.training_session_id is not None and row.training_session_id != session_id:
        raise HTTPException(status_code=409, detail="Экземпляр уже привязан к другому занятию")
    row.training_session_id = session_id
    await database.commit()
    return await read_instance(instance_id, user, database)


@session_router.get("/{session_id}/scenario-instances")
async def list_session_instances(
    session_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    await _session_read(database, session_id, user)
    rows = (
        await database.scalars(
            select(ScenarioInstance)
            .where(ScenarioInstance.training_session_id == session_id)
            .options(selectinload(ScenarioInstance.events))
            .order_by(ScenarioInstance.id)
        )
    ).all()
    return [_serialize(row) for row in rows]


async def _session_read(database: AsyncSession, session_id: int, user: User) -> None:
    session = await database.get(TrainingSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    if user.role != UserRole.ADMIN and session.instructor_id != user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к занятию")
