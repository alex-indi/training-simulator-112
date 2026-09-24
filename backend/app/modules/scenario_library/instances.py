"""Deterministic preparation of instructor-only scenario instances."""

from __future__ import annotations

import random
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
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
from app.modules.scenario_library.instance_models import ScenarioInstance, ScenarioInstanceEvent
from app.modules.scenario_library.router import get_template, readiness_errors, require_editor
from app.modules.training.models import TrainingSession, TrainingSessionState

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


def _event_dict(row) -> dict:
    return {
        "sequence_number": row.sequence_number,
        "offset_seconds": row.offset_seconds,
        "event_type": row.event_type,
        "title": row.title,
        "description": row.description,
        "source_type": row.source_type,
        "payload_snapshot": {
            "title": row.title,
            "description": row.description,
            "source_type": row.source_type,
        },
    }


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
            "description": template.initial_description,
            "caller_text": template.initial_caller_text,
        },
        "events": [_event_dict(event) for event in template.events],
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
        "events": [_event_dict(e) for e in row.events],
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
    row = ScenarioInstance(
        scenario_template_id=template_id,
        training_session_id=data.training_session_id,
        created_by_user_id=user.id,
        name=content["name"],
        difficulty=content["difficulty"],
        generation_seed=data.seed,
        classifier_snapshot=content["classifier_snapshot"],
        object_snapshot=content["object_snapshot"],
        service_snapshot=content["service_snapshot"],
        initial_state_snapshot=content["initial_state_snapshot"],
        expected_actions_snapshot=content["expected_actions_snapshot"],
        assessment_criteria_snapshot=content["assessment_criteria_snapshot"],
        template_snapshot=content["template_snapshot"],
        events=[ScenarioInstanceEvent(**event) for event in content["events"]],
    )
    database.add(row)
    await database.commit()
    return await read_instance(row.id, user, database)


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
