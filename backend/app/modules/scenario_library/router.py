"""API библиотеки сценариев; обучаемым не раскрывает методический план."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incident_classifier.models import (
    DispatchService,
    IncidentClassifierRule,
    IncidentRuleService,
)
from app.modules.object_registry.models import (
    CityObject,
    ObjectTag,
    ObjectTagDefinition,
    ObjectType,
)
from app.modules.object_registry.queries import descendant_type_ids
from app.modules.scenario_library.models import (
    ScenarioAssessmentCriterion,
    ScenarioEventTemplate,
    ScenarioExpectedAction,
    ScenarioTemplate,
    ScenarioTemplateObjectRule,
    ScenarioTemplateRequiredObjectTag,
    ScenarioTemplateService,
)

router = APIRouter(prefix="/api/scenario-templates", tags=["scenario-templates"])
EVENT_TYPES = {
    "INITIAL_REPORT",
    "ADDITIONAL_INFO",
    "RESPONSE_MESSAGE",
    "SITUATION_CHANGE",
    "SYSTEM_EVENT",
}
RESPONSE_PROGRESS_STATES = (
    "ASSIGNED",
    "ACKNOWLEDGED",
    "EN_ROUTE",
    "ARRIVED",
    "WORKING",
    "COMPLETED",
)


class ObjectRuleInput(BaseModel):
    selection_mode: Literal["GENERIC", "OBJECT_BOUND"]
    object_type_id: int
    specific_object_id: int | None = None
    required_tags: list[str] = Field(default_factory=list)


class EventInput(BaseModel):
    offset_seconds: int = Field(ge=0)
    event_type: str
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    source_type: str = "SYSTEM"
    target_service_id: int | None = Field(default=None, gt=0)
    target_response_state: (
        Literal["ACKNOWLEDGED", "EN_ROUTE", "ARRIVED", "WORKING", "COMPLETED"] | None
    ) = None


class ServiceInput(BaseModel):
    service_id: int
    source: Literal["CLASSIFIER", "MANUAL"] = "MANUAL"


class ActionInput(BaseModel):
    expected_action_type: str = Field(min_length=1, max_length=80)
    target_status: str | None = None
    expected_service_id: int | None = None
    deadline_seconds: int | None = Field(default=None, ge=0)
    is_critical: bool = False
    description: str = ""


class CriterionInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    weight: int | None = Field(default=None, ge=0)
    is_critical: bool = False


class TemplateInput(BaseModel):
    name: str = Field(default="", max_length=200)
    description: str = ""
    difficulty: int = Field(default=3, ge=1, le=5)
    classifier_rule_id: int | None = None
    object_rule: ObjectRuleInput | None = None
    initial_title: str = Field(default="", max_length=200)
    initial_description: str = ""
    initial_caller_text: str = ""
    events: list[EventInput] = Field(default_factory=list)
    services: list[ServiceInput] = Field(default_factory=list)
    expected_actions: list[ActionInput] = Field(default_factory=list)
    criteria: list[CriterionInput] = Field(default_factory=list)
    created_by_user_id: int | None = Field(default=None, gt=0)


async def require_editor(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise HTTPException(
            status_code=403, detail="Библиотека доступна преподавателю и администратору"
        )
    return user


def detail_options():
    return (
        selectinload(ScenarioTemplate.classifier_rule),
        selectinload(ScenarioTemplate.object_rule).selectinload(
            ScenarioTemplateObjectRule.required_tags
        ),
        selectinload(ScenarioTemplate.object_rule).selectinload(
            ScenarioTemplateObjectRule.specific_object
        ),
        selectinload(ScenarioTemplate.events),
        selectinload(ScenarioTemplate.services),
        selectinload(ScenarioTemplate.expected_actions),
        selectinload(ScenarioTemplate.criteria),
    )


async def get_template(database: AsyncSession, template_id: int) -> ScenarioTemplate:
    row = (
        await database.scalars(
            select(ScenarioTemplate)
            .where(ScenarioTemplate.id == template_id)
            .options(*detail_options())
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Сценарий не найден")
    return row


async def resolve_author(database: AsyncSession, user: User, author_id: int | None) -> int:
    if author_id is None:
        return user.id
    if user.role != UserRole.ADMIN and author_id != user.id:
        raise HTTPException(status_code=403, detail="Назначать автора может только администратор")
    author = await database.get(User, author_id)
    if author is None or author.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise HTTPException(
            status_code=422,
            detail="Автором сценария может быть преподаватель или администратор",
        )
    return author.id


def can_archive(row: ScenarioTemplate, user: User) -> bool:
    """READY-сценарий архивирует только его автор или администратор."""
    return user.role == UserRole.ADMIN or row.created_by_user_id == user.id


def serialize(row: ScenarioTemplate) -> dict:
    rule = row.object_rule
    return {
        "id": row.id,
        "seed_code": row.seed_code,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "difficulty": row.difficulty,
        "version": row.version,
        "classifier_rule_id": row.classifier_rule_id,
        "incident_group": row.classifier_rule.incident_group if row.classifier_rule else None,
        "incident_type": row.classifier_rule.final_incident_type if row.classifier_rule else None,
        "created_by_user_id": row.created_by_user_id,
        "initial_title": row.initial_title,
        "initial_description": row.initial_description,
        "initial_caller_text": row.initial_caller_text,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "archived_at": row.archived_at,
        "object_rule": None
        if rule is None
        else {
            "selection_mode": rule.selection_mode,
            "object_type_id": rule.object_type_id,
            "specific_object_id": rule.specific_object_id,
            "specific_object_name": rule.specific_object.name if rule.specific_object else None,
            "district": rule.specific_object.district if rule.specific_object else None,
            "required_tags": [tag.tag for tag in rule.required_tags],
        },
        "events": [
            {
                "id": event.id,
                "offset_seconds": event.offset_seconds,
                "event_type": event.event_type,
                "title": event.title,
                "description": event.description,
                "source_type": event.source_type,
                "target_service_id": event.target_service_id,
                "target_response_state": event.target_response_state,
            }
            for event in row.events
        ],
        "services": [
            {"service_id": link.service_id, "source": link.source} for link in row.services
        ],
        "expected_actions": [
            {
                "id": action.id,
                "expected_action_type": action.expected_action_type,
                "target_status": action.target_status,
                "expected_service_id": action.expected_service_id,
                "deadline_seconds": action.deadline_seconds,
                "is_critical": action.is_critical,
                "description": action.description,
            }
            for action in row.expected_actions
        ],
        "criteria": [
            {
                "id": criterion.id,
                "name": criterion.name,
                "description": criterion.description,
                "weight": criterion.weight,
                "is_critical": criterion.is_critical,
            }
            for criterion in row.criteria
        ],
    }


async def matching_object_count(
    database: AsyncSession, rule: ScenarioTemplateObjectRule | ObjectRuleInput
) -> int:
    type_code = await database.scalar(
        select(ObjectType.code).where(ObjectType.id == rule.object_type_id)
    )
    if type_code is None:
        return 0
    query = select(func.count(CityObject.id)).where(
        CityObject.object_type_id.in_(descendant_type_ids(type_code))
    )
    if rule.selection_mode == "OBJECT_BOUND":
        query = query.where(CityObject.id == rule.specific_object_id)
    tags = rule.required_tags
    for tag in tags:
        value = tag if isinstance(tag, str) else tag.tag
        query = query.where(
            CityObject.id.in_(select(ObjectTag.object_id).where(ObjectTag.tag == value))
        )
    return int((await database.scalar(query)) or 0)


async def validate_references(database: AsyncSession, data: TemplateInput) -> None:
    if (
        data.classifier_rule_id is not None
        and await database.get(IncidentClassifierRule, data.classifier_rule_id) is None
    ):
        raise HTTPException(status_code=422, detail="Неизвестное правило SRC-006")
    if data.object_rule is not None:
        rule = data.object_rule
        object_type = await database.get(ObjectType, rule.object_type_id)
        if object_type is None or not object_type.is_active:
            raise HTTPException(status_code=422, detail="Неизвестный или неактивный ObjectType")
        if (rule.selection_mode == "GENERIC") != (rule.specific_object_id is None):
            raise HTTPException(
                status_code=422, detail="Режим выбора объекта и конкретный объект не согласованы"
            )
        if rule.specific_object_id is not None:
            city_object = await database.get(CityObject, rule.specific_object_id)
            if city_object is None:
                raise HTTPException(status_code=422, detail="Неизвестный объект Москвы")
            type_code = object_type.code
            accepted = await database.scalar(
                select(func.count())
                .select_from(ObjectType)
                .where(
                    ObjectType.id == city_object.object_type_id,
                    ObjectType.id.in_(descendant_type_ids(type_code)),
                )
            )
            if not accepted:
                raise HTTPException(
                    status_code=422, detail="Тип конкретного объекта не соответствует правилу"
                )
            for tag in set(rule.required_tags):
                exists = await database.scalar(
                    select(func.count())
                    .select_from(ObjectTag)
                    .where(ObjectTag.object_id == city_object.id, ObjectTag.tag == tag)
                )
                if not exists:
                    raise HTTPException(status_code=422, detail=f"У объекта нет тега {tag}")
        for tag in set(rule.required_tags):
            if await database.get(ObjectTagDefinition, tag) is None:
                raise HTTPException(status_code=422, detail=f"Неизвестный тег объекта {tag}")
    if len({service.service_id for service in data.services}) != len(data.services):
        raise HTTPException(status_code=422, detail="Служба указана дважды")
    for service_id in (
        {service.service_id for service in data.services}
        | {
            action.expected_service_id
            for action in data.expected_actions
            if action.expected_service_id is not None
        }
        | {event.target_service_id for event in data.events if event.target_service_id is not None}
    ):
        if await database.get(DispatchService, service_id) is None:
            raise HTTPException(status_code=422, detail=f"Неизвестная служба {service_id}")
    if data.classifier_rule_id is None and any(
        service.source == "CLASSIFIER" for service in data.services
    ):
        raise HTTPException(
            status_code=422, detail="Для службы классификатора нужно выбрать правило"
        )
    for service in data.services:
        if service.source == "CLASSIFIER":
            exists = await database.scalar(
                select(func.count())
                .select_from(IncidentRuleService)
                .where(
                    IncidentRuleService.rule_id == data.classifier_rule_id,
                    IncidentRuleService.service_id == service.service_id,
                )
            )
            if not exists:
                raise HTTPException(
                    status_code=422, detail="Служба не связана с выбранным правилом SRC-006"
                )
    if any(event.event_type not in EVENT_TYPES for event in data.events):
        raise HTTPException(status_code=422, detail="Неизвестный тип события")
    service_ids = {service.service_id for service in data.services}
    if any(
        event.target_service_id is not None and event.target_service_id not in service_ids
        for event in data.events
    ):
        raise HTTPException(status_code=422, detail="Служба сообщения должна входить в сценарий")
    if any(
        event.target_response_state is not None
        and (event.event_type != "RESPONSE_MESSAGE" or event.target_service_id is None)
        for event in data.events
    ):
        raise HTTPException(status_code=422, detail="Состояние группы требует адресного сообщения")
    if len(data.events) > 100:
        raise HTTPException(status_code=422, detail="Слишком много событий")


def populate(row: ScenarioTemplate, data: TemplateInput) -> None:
    row.name = data.name.strip()
    row.description = data.description
    row.difficulty = data.difficulty
    row.classifier_rule_id = data.classifier_rule_id
    row.initial_title = data.initial_title.strip()
    row.initial_description = data.initial_description
    row.initial_caller_text = data.initial_caller_text
    row.object_rule = (
        None
        if data.object_rule is None
        else ScenarioTemplateObjectRule(
            selection_mode=data.object_rule.selection_mode,
            object_type_id=data.object_rule.object_type_id,
            specific_object_id=data.object_rule.specific_object_id,
            required_tags=[
                ScenarioTemplateRequiredObjectTag(tag=tag)
                for tag in sorted(set(data.object_rule.required_tags))
            ],
        )
    )
    row.events = [
        ScenarioEventTemplate(sequence_number=index, **event.model_dump())
        for index, event in enumerate(data.events)
    ]
    row.services = [ScenarioTemplateService(**service.model_dump()) for service in data.services]
    row.expected_actions = [
        ScenarioExpectedAction(**action.model_dump()) for action in data.expected_actions
    ]
    row.criteria = [
        ScenarioAssessmentCriterion(**criterion.model_dump()) for criterion in data.criteria
    ]
    row.updated_at = datetime.now(UTC)


def as_input(row: ScenarioTemplate) -> TemplateInput:
    data = serialize(row)
    return TemplateInput.model_validate({key: data[key] for key in TemplateInput.model_fields})


async def readiness_errors(database: AsyncSession, row: ScenarioTemplate) -> list[str]:
    errors: list[str] = []
    if not row.name.strip():
        errors.append("Укажите название")
    if row.classifier_rule_id is None:
        errors.append("Выберите правило SRC-006")
    if row.object_rule is None:
        errors.append("Задайте правило выбора объекта")
    elif await matching_object_count(database, row.object_rule) == 0:
        errors.append("Нет подходящих объектов")
    if not row.initial_title.strip() or not row.initial_description.strip():
        errors.append("Заполните исходную карточку")
    initial = [event for event in row.events if event.event_type == "INITIAL_REPORT"]
    if len(initial) != 1 or initial[0].offset_seconds != 0:
        errors.append("Нужно одно начальное событие на 0 секунд")
    if any(
        row.events[i].offset_seconds > row.events[i + 1].offset_seconds
        for i in range(len(row.events) - 1)
    ):
        errors.append("Временная шкала событий должна идти по порядку")
    if row.events and row.events[0].event_type != "INITIAL_REPORT":
        errors.append("Первым должно идти начальное событие")
    service_ids = {service.service_id for service in row.services}
    service_states = {service_id: "ASSIGNED" for service_id in service_ids}
    for event in row.events:
        if event.event_type == "RESPONSE_MESSAGE":
            if event.target_service_id is None:
                errors.append("Выберите службу для сообщения группы")
            elif event.target_service_id not in service_ids:
                errors.append("Служба сообщения должна входить в сценарий")
            if (
                event.target_response_state is not None
                and event.target_service_id in service_states
            ):
                state = event.target_response_state
                previous = service_states[event.target_service_id]
                if (
                    state not in RESPONSE_PROGRESS_STATES
                    or RESPONSE_PROGRESS_STATES.index(state)
                    != RESPONSE_PROGRESS_STATES.index(previous) + 1
                ):
                    errors.append("Неверная последовательность состояний группы")
                else:
                    service_states[event.target_service_id] = state
        elif event.target_response_state is not None:
            errors.append("Состояние группы требует сообщения службы")
    return errors


@router.get("/catalog")
async def catalog(
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
    q: str = "",
) -> dict:
    term = f"%{q.strip()}%"
    rules = (
        await database.scalars(
            select(IncidentClassifierRule)
            .where(
                or_(
                    IncidentClassifierRule.final_incident_type.ilike(term),
                    IncidentClassifierRule.incident_group.ilike(term),
                    IncidentClassifierRule.source_code.ilike(term),
                )
            )
            .order_by(IncidentClassifierRule.id)
            .limit(200)
        )
    ).all()
    object_types = (
        await database.scalars(
            select(ObjectType).where(ObjectType.is_active.is_(True)).order_by(ObjectType.name)
        )
    ).all()
    services = (
        await database.scalars(select(DispatchService).order_by(DispatchService.official_name))
    ).all()
    tags = (
        await database.scalars(select(ObjectTagDefinition).order_by(ObjectTagDefinition.name))
    ).all()
    authors = (
        await database.scalars(
            select(User)
            .where(User.role.in_([UserRole.INSTRUCTOR, UserRole.ADMIN]))
            .order_by(User.full_name)
        )
    ).all()
    objects = (
        (
            await database.scalars(
                select(CityObject)
                .where(or_(CityObject.name.ilike(term), CityObject.address.ilike(term)))
                .order_by(CityObject.name)
                .limit(100)
            )
        ).all()
        if q.strip()
        else []
    )
    return {
        "rules": [
            {
                "id": row.id,
                "group": row.incident_group,
                "type": row.final_incident_type,
                "source_code": row.source_code,
            }
            for row in rules
        ],
        "object_types": [
            {"id": row.id, "code": row.code, "name": row.name, "parent_id": row.parent_id}
            for row in object_types
        ],
        "services": [{"id": row.id, "name": row.official_name} for row in services],
        "tags": [{"code": row.code, "name": row.name} for row in tags],
        "authors": [{"id": row.id, "name": row.full_name} for row in authors],
        "objects": [
            {
                "id": row.id,
                "name": row.name,
                "address": row.address,
                "district": row.district,
                "administrative_area": row.administrative_area,
                "object_type_id": row.object_type_id,
            }
            for row in objects
        ],
        "user_id": user.id,
    }


@router.get("")
async def list_templates(
    _user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
    q: str = "",
    status: str = "READY",
    difficulty: int | None = None,
    classifier_rule_id: int | None = None,
    incident_group: str | None = None,
    incident_type: str | None = None,
    object_type_id: int | None = None,
    district: str | None = None,
    administrative_area: str | None = None,
    service_id: int | None = None,
    created_by: int | None = None,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    query = select(ScenarioTemplate).options(*detail_options())
    if status != "ALL":
        query = query.where(ScenarioTemplate.status == status)
    if q.strip():
        query = query.where(ScenarioTemplate.name.ilike(f"%{q.strip()}%"))
    if difficulty is not None:
        query = query.where(ScenarioTemplate.difficulty == difficulty)
    if classifier_rule_id is not None:
        query = query.where(ScenarioTemplate.classifier_rule_id == classifier_rule_id)
    if incident_group or incident_type:
        classifier = select(IncidentClassifierRule.id)
        if incident_group:
            classifier = classifier.where(
                IncidentClassifierRule.incident_group.ilike(f"%{incident_group.strip()}%")
            )
        if incident_type:
            classifier = classifier.where(
                IncidentClassifierRule.final_incident_type.ilike(f"%{incident_type.strip()}%")
            )
        query = query.where(ScenarioTemplate.classifier_rule_id.in_(classifier))
    if created_by is not None:
        query = query.where(ScenarioTemplate.created_by_user_id == created_by)
    if object_type_id is not None:
        query = query.where(
            ScenarioTemplate.id.in_(
                select(ScenarioTemplateObjectRule.scenario_template_id).where(
                    ScenarioTemplateObjectRule.object_type_id == object_type_id
                )
            )
        )
    if service_id is not None:
        query = query.where(
            ScenarioTemplate.id.in_(
                select(ScenarioTemplateService.scenario_template_id).where(
                    ScenarioTemplateService.service_id == service_id
                )
            )
        )
    if district or administrative_area:
        bound = select(ScenarioTemplateObjectRule.scenario_template_id).join(
            CityObject, CityObject.id == ScenarioTemplateObjectRule.specific_object_id
        )
        if district:
            bound = bound.where(CityObject.district == district)
        if administrative_area:
            bound = bound.where(CityObject.administrative_area == administrative_area)
        query = query.where(ScenarioTemplate.id.in_(bound))
    total = await database.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = (
        await database.scalars(
            query.order_by(ScenarioTemplate.updated_at.desc(), ScenarioTemplate.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{template_id}")
async def read_template(
    template_id: int,
    _user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    return serialize(await get_template(database, template_id))


@router.post("", status_code=201)
async def create_template(
    data: TemplateInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    await validate_references(database, data)
    author_id = await resolve_author(database, user, data.created_by_user_id)
    row = ScenarioTemplate(created_by_user_id=author_id)
    populate(row, data)
    database.add(row)
    await database.commit()
    return serialize(await get_template(database, row.id))


@router.patch("/{template_id}")
async def update_template(
    template_id: int,
    data: TemplateInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    row = await get_template(database, template_id)
    if row.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Редактируется только черновик; создайте копию")
    await validate_references(database, data)
    if data.created_by_user_id is not None:
        row.created_by_user_id = await resolve_author(database, user, data.created_by_user_id)
    row.object_rule = None
    row.events = []
    row.services = []
    row.expected_actions = []
    row.criteria = []
    await database.flush()
    populate(row, data)
    row.version += 1
    await database.commit()
    return serialize(await get_template(database, template_id))


@router.get("/{template_id}/validate")
async def validate_template(
    template_id: int,
    _user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    row = await get_template(database, template_id)
    return {
        "errors": await readiness_errors(database, row),
        "matching_object_count": await matching_object_count(database, row.object_rule)
        if row.object_rule
        else 0,
    }


@router.post("/{template_id}/ready")
async def ready_template(
    template_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    row = await get_template(database, template_id)
    if row.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Только черновик можно перевести в READY")
    errors = await readiness_errors(database, row)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    row.status = "READY"
    row.updated_at = datetime.now(UTC)
    await database.commit()
    return serialize(await get_template(database, template_id))


@router.post("/{template_id}/archive")
async def archive_template(
    template_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    row = await get_template(database, template_id)
    if row.status != "READY":
        raise HTTPException(status_code=409, detail="Архивируется только READY-сценарий")
    if not can_archive(row, user):
        raise HTTPException(
            status_code=403,
            detail="Архивировать сценарий может только его автор или администратор",
        )
    row.status = "ARCHIVED"
    row.archived_at = datetime.now(UTC)
    row.updated_at = row.archived_at
    await database.commit()
    return serialize(await get_template(database, template_id))


@router.post("/{template_id}/duplicate", status_code=201)
async def duplicate_template(
    template_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    original = await get_template(database, template_id)
    data = as_input(original)
    data.name = f"{original.name} — копия"[:200]
    row = ScenarioTemplate(created_by_user_id=user.id)
    populate(row, data)
    database.add(row)
    await database.commit()
    return serialize(await get_template(database, row.id))
