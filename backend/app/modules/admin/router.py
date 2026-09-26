"""Administrative REST API isolated from instructor and trainee operations."""

import json
from datetime import UTC, datetime
from os import getenv
from typing import Annotated, Any, cast
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.dependencies import get_database_session
from app.modules.admin.data_exchange import (
    DatasetKey,
    ImportEnvelope,
    export_dataset,
    import_dataset,
)
from app.modules.admin.dependencies import require_admin
from app.modules.admin.models import (
    AdminAudit,
    AIProviderConfig,
    AIUsageDaily,
    DataQualityIssue,
    ImportRun,
    UserGroup,
)
from app.modules.admin.schemas import (
    AdminUserRead,
    AIConfigRead,
    AIConfigUpdate,
    AIModelCatalogRead,
    AIModelCatalogRequest,
    AIUsageRead,
    AuditRead,
    ClassifierRead,
    ClassifierUpdate,
    DataQualityRead,
    ImportRunRead,
    ObjectTypeRead,
    ObjectTypeUpdate,
    ObjectTypeWrite,
    RegistryObjectRead,
    RegistryObjectUpdate,
    ScenarioAdminRead,
    ServiceRead,
    ServiceUpdate,
    UserCreate,
    UserGroupCreate,
    UserGroupRead,
    UserGroupUpdate,
    UserUpdate,
)
from app.modules.admin.secrets import decrypt_api_key, encrypt_api_key
from app.modules.identity.models import User, UserRole
from app.modules.identity.passwords import hash_password
from app.modules.incident_classifier.models import (
    DispatchService,
    IncidentClassifierRule,
    IncidentFeature,
    IncidentRuleFeature,
    IncidentRuleService,
)
from app.modules.object_registry.models import (
    CityObject,
    ObjectAttribute,
    ObjectTag,
    ObjectTagDefinition,
    ObjectType,
)
from app.modules.scenario_library.models import ScenarioTemplate
from app.services.text_generation.providers import OpenAICompatibleProvider, OpenAIProvider
from app.services.text_generation.renderer import TemplateTextGenerationProvider

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

Database = Annotated[AsyncSession, Depends(get_database_session)]
Admin = Annotated[User, Depends(require_admin)]

IMPORT_DATASETS: dict[str, dict[str, str]] = {
    "classifier": {
        "name": "Классификатор происшествий",
        "description": "Правила SRC-006, признаки и связи со службами реагирования.",
    },
    "services": {
        "name": "Службы 112",
        "description": "Диспетчерские службы, организации и уровень обслуживания.",
    },
    "objects": {
        "name": "Объекты Москвы",
        "description": "Типы, объекты, характеристики и поисковые теги реестра.",
    },
}


def _audit(
    admin: User,
    action: str,
    entity_type: str,
    entity_id: int | str | None,
    before: dict | None = None,
    after: dict | None = None,
) -> AdminAudit:
    return AdminAudit(
        admin_id=admin.id,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        before=before,
        after=after,
    )


def _user_snapshot(user: User) -> dict[str, Any]:
    return {
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.value,
        "is_active": user.is_active,
        "group_id": user.group_id,
    }


async def _one_or_404(session: AsyncSession, model: type, entity_id: int):
    entity = await session.get(model, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return entity


def _dataset_or_404(source: str) -> DatasetKey:
    if source not in IMPORT_DATASETS:
        raise HTTPException(status_code=404, detail="Набор данных не найден")
    return cast(DatasetKey, source)


@router.get("/dashboard")
async def dashboard(session: Database) -> dict[str, Any]:
    async def count(model: type, *criteria: Any) -> int:
        statement = select(func.count()).select_from(model)
        if criteria:
            statement = statement.where(*criteria)
        return int((await session.scalar(statement)) or 0)

    last_import = await session.scalar(
        select(ImportRun).order_by(ImportRun.started_at.desc()).limit(1)
    )
    ai_config = await session.get(AIProviderConfig, 1) or _ai_from_environment()
    return {
        "users": await count(User),
        "active_users": await count(User, User.is_active.is_(True)),
        "user_groups": await count(UserGroup),
        "ready_scenarios": await count(ScenarioTemplate, ScenarioTemplate.status == "READY"),
        "classifier_rules": await count(IncidentClassifierRule),
        "services": await count(DispatchService),
        "objects": await count(CityObject),
        "data_quality_open": await count(DataQualityIssue, DataQualityIssue.status == "OPEN"),
        "ai": {
            "enabled": ai_config.enabled,
            "provider": ai_config.provider,
            "model": ai_config.model,
            "api_key_configured": _ai_api_key_configured(ai_config),
        },
        "last_import": ImportRunRead.model_validate(last_import) if last_import else None,
    }


@router.get("/users", response_model=list[AdminUserRead])
async def list_users(session: Database) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.id))).all())


@router.get("/user-groups", response_model=list[UserGroupRead])
async def list_user_groups(session: Database) -> list[UserGroupRead]:
    rows = (
        await session.execute(
            select(UserGroup, func.count(User.id))
            .outerjoin(User, User.group_id == UserGroup.id)
            .group_by(UserGroup.id)
            .order_by(UserGroup.name)
        )
    ).all()
    return [
        UserGroupRead(
            id=group.id,
            name=group.name,
            description=group.description,
            member_count=int(member_count),
        )
        for group, member_count in rows
    ]


@router.post("/user-groups", response_model=UserGroupRead, status_code=status.HTTP_201_CREATED)
async def create_user_group(
    payload: UserGroupCreate, session: Database, admin: Admin
) -> UserGroupRead:
    name = payload.name.strip()
    if await session.scalar(select(UserGroup.id).where(func.lower(UserGroup.name) == name.lower())):
        raise HTTPException(status_code=409, detail="Группа с таким названием уже существует")
    group = UserGroup(name=name, description=payload.description.strip())
    session.add(group)
    await session.flush()
    session.add(
        _audit(
            admin,
            "USER_GROUP_CREATED",
            "USER_GROUP",
            group.id,
            after={"name": group.name, "description": group.description},
        )
    )
    await session.commit()
    return UserGroupRead(
        id=group.id,
        name=group.name,
        description=group.description,
        member_count=0,
    )


@router.patch("/user-groups/{group_id}", response_model=UserGroupRead)
async def update_user_group(
    group_id: int, payload: UserGroupUpdate, session: Database, admin: Admin
) -> UserGroupRead:
    group: UserGroup = await _one_or_404(session, UserGroup, group_id)
    before = {"name": group.name, "description": group.description}
    if payload.name is not None:
        name = payload.name.strip()
        duplicate = await session.scalar(
            select(UserGroup.id).where(
                func.lower(UserGroup.name) == name.lower(),
                UserGroup.id != group.id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Группа с таким названием уже существует")
        group.name = name
    if payload.description is not None:
        group.description = payload.description.strip()
    after = {"name": group.name, "description": group.description}
    session.add(_audit(admin, "USER_GROUP_UPDATED", "USER_GROUP", group.id, before, after))
    await session.commit()
    member_count_query = select(func.count()).select_from(User).where(User.group_id == group.id)
    member_count = int((await session.scalar(member_count_query)) or 0)
    return UserGroupRead(
        id=group.id,
        name=group.name,
        description=group.description,
        member_count=member_count,
    )


@router.delete("/user-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_group(group_id: int, session: Database, admin: Admin) -> None:
    group: UserGroup = await _one_or_404(session, UserGroup, group_id)
    before = {"name": group.name, "description": group.description}
    from app.modules.training.models import TrainingGroup

    used = await session.scalar(
        select(TrainingGroup.id).where(TrainingGroup.source_user_group_id == group.id)
    )
    if used is not None:
        group.is_archived = True
        session.add(_audit(admin, "USER_GROUP_ARCHIVED", "USER_GROUP", group.id, before=before))
        await session.commit()
        return
    await session.execute(sql_update(User).where(User.group_id == group.id).values(group_id=None))
    await session.delete(group)
    session.add(_audit(admin, "USER_GROUP_DELETED", "USER_GROUP", group.id, before=before))
    await session.commit()


async def _validate_user_group(session: AsyncSession, role: UserRole, group_id: int | None) -> None:
    if group_id is not None and role != UserRole.TRAINEE:
        raise HTTPException(status_code=422, detail="Группы доступны только диспетчерам ДДС")
    if group_id is not None and await session.get(UserGroup, group_id) is None:
        raise HTTPException(status_code=404, detail="Группа пользователей не найдена")


@router.post("/users", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, session: Database, admin: Admin) -> User:
    username = payload.username.strip().lower()
    if await session.scalar(select(User.id).where(User.username == username)):
        raise HTTPException(status_code=409, detail="Пользователь с таким логином уже существует")
    await _validate_user_group(session, payload.role, payload.group_id)
    user = User(
        username=username,
        full_name=payload.full_name.strip(),
        role=payload.role,
        password_hash=hash_password(payload.password),
        group_id=payload.group_id,
    )
    session.add(user)
    await session.flush()
    session.add(_audit(admin, "USER_CREATED", "USER", user.id, after=_user_snapshot(user)))
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(user_id: int, payload: UserUpdate, session: Database, admin: Admin) -> User:
    user: User = await _one_or_404(session, User, user_id)
    before = _user_snapshot(user)
    next_username = (
        payload.username.strip().lower() if payload.username is not None else user.username
    )
    if next_username != user.username and await session.scalar(
        select(User.id).where(User.username == next_username, User.id != user.id)
    ):
        raise HTTPException(status_code=409, detail="Пользователь с таким логином уже существует")
    next_role = payload.role if payload.role is not None else user.role
    next_group_id = payload.group_id if "group_id" in payload.model_fields_set else user.group_id
    if next_role != UserRole.TRAINEE:
        next_group_id = None
    await _validate_user_group(session, next_role, next_group_id)
    next_active = payload.is_active if payload.is_active is not None else user.is_active
    removes_active_admin = (
        user.role == UserRole.ADMIN
        and user.is_active
        and (next_role != UserRole.ADMIN or not next_active)
    )
    if removes_active_admin:
        active_admins = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
        )
        if int(active_admins or 0) <= 1:
            raise HTTPException(
                status_code=409, detail="Нельзя отключить последнего активного администратора"
            )
    if payload.username is not None:
        user.username = next_username
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.role is not None:
        user.role = payload.role
    user.group_id = next_group_id
    if payload.is_active is not None:
        user.is_active = payload.is_active
    after = _user_snapshot(user)
    action = "USER_UPDATED"
    if before["role"] != after["role"]:
        action = "USER_ROLE_CHANGED"
    elif before["is_active"] != after["is_active"]:
        action = "USER_ACTIVATION_CHANGED"
    elif before["username"] != after["username"] or payload.password is not None:
        action = "USER_CREDENTIALS_CHANGED"
    session.add(_audit(admin, action, "USER", user.id, before, after))
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, session: Database, admin: Admin) -> None:
    user: User = await _one_or_404(session, User, user_id)
    if user.id == admin.id:
        raise HTTPException(
            status_code=409,
            detail="Нельзя удалить текущую учётную запись администратора",
        )
    before = _user_snapshot(user)
    session.add(_audit(admin, "USER_DELETED", "USER", user.id, before=before))
    await session.delete(user)
    try:
        await session.commit()
    except IntegrityError as cause:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=("Пользователь связан с учебной историей. Деактивируйте его вместо удаления."),
        ) from cause


def _classifier_read(row: IncidentClassifierRule) -> ClassifierRead:
    feature_links = sorted(row.features, key=lambda link: int(link.feature.level))
    return ClassifierRead(
        id=row.id,
        source_code=row.source_code,
        incident_group=row.incident_group,
        feature_1=feature_links[0].feature.name if len(feature_links) > 0 else None,
        feature_2=feature_links[1].feature.name if len(feature_links) > 1 else None,
        feature_3=feature_links[2].feature.name if len(feature_links) > 2 else None,
        incident_type=row.final_incident_type,
        related_services=[link.service.official_name for link in row.services],
        related_service_ids=[link.service_id for link in row.services],
    )


def _classifier_snapshot(row: IncidentClassifierRule) -> dict[str, Any]:
    return _classifier_read(row).model_dump(mode="json")


@router.get("/classifier", response_model=list[ClassifierRead])
async def classifier(
    session: Database,
    search: str = "",
    incident_group: str = "",
    service: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ClassifierRead]:
    statement = select(IncidentClassifierRule).options(
        selectinload(IncidentClassifierRule.features).selectinload(IncidentRuleFeature.feature),
        selectinload(IncidentClassifierRule.services).selectinload(IncidentRuleService.service),
    )
    if search:
        value = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                IncidentClassifierRule.final_incident_type.ilike(value),
                IncidentClassifierRule.source_code.ilike(value),
            )
        )
    if incident_group:
        statement = statement.where(IncidentClassifierRule.incident_group == incident_group)
    rows = list(
        (await session.scalars(statement.order_by(IncidentClassifierRule.id).limit(limit))).all()
    )
    result = [_classifier_read(row) for row in rows]
    if service:
        needle = service.casefold()
        result = [
            row for row in result if any(needle in name.casefold() for name in row.related_services)
        ]
    return result


@router.patch("/classifier/{rule_id}", response_model=ClassifierRead)
async def update_classifier_rule(
    rule_id: int, payload: ClassifierUpdate, session: Database, admin: Admin
) -> ClassifierRead:
    statement = (
        select(IncidentClassifierRule)
        .where(IncidentClassifierRule.id == rule_id)
        .options(
            selectinload(IncidentClassifierRule.features).selectinload(
                IncidentRuleFeature.feature
            ),
            selectinload(IncidentClassifierRule.services).selectinload(
                IncidentRuleService.service
            ),
        )
    )
    rule = await session.scalar(statement)
    if rule is None:
        raise HTTPException(status_code=404, detail="Правило классификатора не найдено")
    before = _classifier_snapshot(rule)
    changes = payload.model_dump(exclude_unset=True)
    if "source_code" in changes:
        rule.source_code = changes["source_code"] or None
    if "incident_group" in changes:
        rule.incident_group = changes["incident_group"].strip()
    if "incident_type" in changes:
        rule.final_incident_type = changes["incident_type"].strip()
    if payload.feature_names is not None:
        rule.features.clear()
        columns = ("112 - Признак.1 (тип происшествия)", "112-Признак.2", "112-Признак.3")
        for index, raw_name in enumerate(payload.feature_names, start=1):
            name = raw_name.strip()
            if not name:
                continue
            feature = await session.scalar(
                select(IncidentFeature).where(
                    IncidentFeature.level == str(index),
                    func.lower(IncidentFeature.name) == name.lower(),
                )
            )
            if feature is None:
                feature = IncidentFeature(
                    name=name,
                    level=str(index),
                    source_column=columns[index - 1],
                    source_value=name,
                )
                session.add(feature)
            rule.features.append(IncidentRuleFeature(feature=feature))
    if payload.related_service_ids is not None:
        service_ids = list(dict.fromkeys(payload.related_service_ids))
        selected_services = list(
            (
                await session.scalars(
                    select(DispatchService).where(DispatchService.id.in_(service_ids))
                )
            ).all()
        )
        if len(selected_services) != len(service_ids):
            raise HTTPException(status_code=422, detail="Одна из выбранных служб не найдена")
        rule.services.clear()
        for service_item in selected_services:
            rule.services.append(
                IncidentRuleService(service=service_item, source_reference="ADMIN")
            )
    await session.flush()
    after = _classifier_snapshot(rule)
    session.add(_audit(admin, "CLASSIFIER_RULE_UPDATED", "CLASSIFIER_RULE", rule.id, before, after))
    await session.commit()
    return _classifier_read(rule)


def _service_read(row: DispatchService) -> ServiceRead:
    return ServiceRead(
        id=row.id,
        official_name=row.official_name,
        service_type="Диспетчерская служба",
        level=row.service_level,
        organization=row.organization,
        source="SRC-006",
        data_status="VALID",
        external_id=row.source_reference,
    )


@router.get("/services", response_model=list[ServiceRead])
async def services(
    session: Database,
    search: str = "",
    level: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ServiceRead]:
    statement = select(DispatchService)
    if search:
        statement = statement.where(DispatchService.official_name.ilike(f"%{search.strip()}%"))
    if level:
        statement = statement.where(DispatchService.service_level == level)
    rows = (await session.scalars(statement.order_by(DispatchService.id).limit(limit))).all()
    return [_service_read(row) for row in rows]


@router.patch("/services/{service_id}", response_model=ServiceRead)
async def update_service(
    service_id: int, payload: ServiceUpdate, session: Database, admin: Admin
) -> ServiceRead:
    item: DispatchService = await _one_or_404(session, DispatchService, service_id)
    before = _service_read(item).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    field_map = {
        "official_name": "official_name",
        "level": "service_level",
        "organization": "organization",
        "external_id": "source_reference",
    }
    for source_field, model_field in field_map.items():
        if source_field in changes:
            value = changes[source_field]
            setattr(item, model_field, value.strip() if isinstance(value, str) else value)
    after = _service_read(item).model_dump(mode="json")
    session.add(_audit(admin, "SERVICE_UPDATED", "DISPATCH_SERVICE", item.id, before, after))
    try:
        await session.commit()
    except IntegrityError as cause:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Служба с таким external ID уже существует"
        ) from cause
    return _service_read(item)


def _deserialize_object_attribute(attribute: ObjectAttribute) -> Any:
    """Restore the typed value recorded by the object-registry importer."""
    try:
        if attribute.value_type in {"json", "boolean"}:
            return json.loads(attribute.value)
        if attribute.value_type == "integer":
            return int(attribute.value)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return attribute.value


def _serialize_object_attribute(value: Any) -> tuple[str, str]:
    if isinstance(value, bool):
        return json.dumps(value), "boolean"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True), "json"
    if isinstance(value, int):
        return str(value), "integer"
    return str(value), "text"


def _registry_object_read(row: CityObject) -> RegistryObjectRead:
    return RegistryObjectRead(
        id=row.id,
        official_name=row.name,
        object_type_id=row.object_type_id,
        address=row.address or "",
        district=row.district,
        administrative_area=row.administrative_area,
        latitude=float(row.latitude) if row.latitude is not None else None,
        longitude=float(row.longitude) if row.longitude is not None else None,
        tags=[item.tag for item in row.tags],
        attributes={
            item.attribute_code: _deserialize_object_attribute(item) for item in row.attributes
        },
        source=row.source,
        dataset_id=row.source_dataset_id or "",
        external_id=row.external_id,
    )


@router.get("/object-registry", response_model=list[RegistryObjectRead])
async def object_registry(
    session: Database,
    search: str = "",
    object_type_id: int | None = None,
    district: str = "",
    administrative_area: str = "",
    source: str = "",
    tag: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RegistryObjectRead]:
    statement = select(CityObject).options(
        selectinload(CityObject.tags), selectinload(CityObject.attributes)
    )
    if search:
        value = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                CityObject.name.ilike(value),
                CityObject.address.ilike(value),
            )
        )
    if object_type_id is not None:
        statement = statement.where(CityObject.object_type_id == object_type_id)
    if district:
        statement = statement.where(CityObject.district == district)
    if administrative_area:
        statement = statement.where(CityObject.administrative_area == administrative_area)
    if source:
        statement = statement.where(CityObject.source == source)
    rows = list((await session.scalars(statement.order_by(CityObject.id).limit(limit))).all())
    result = [_registry_object_read(row) for row in rows]
    if tag:
        needle = tag.casefold()
        result = [row for row in result if any(needle in value.casefold() for value in row.tags)]
    return result


@router.patch("/object-registry/{object_id}", response_model=RegistryObjectRead)
async def update_registry_object(
    object_id: int, payload: RegistryObjectUpdate, session: Database, admin: Admin
) -> RegistryObjectRead:
    item = await session.scalar(
        select(CityObject)
        .where(CityObject.id == object_id)
        .options(selectinload(CityObject.tags), selectinload(CityObject.attributes))
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Объект не найден")
    before = _registry_object_read(item).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    if "object_type_id" in changes and payload.object_type_id is None:
        raise HTTPException(status_code=422, detail="Тип объекта обязателен")
    if payload.object_type_id is not None:
        await _one_or_404(session, ObjectType, payload.object_type_id)
    field_map = {
        "official_name": "name",
        "object_type_id": "object_type_id",
        "address": "address",
        "district": "district",
        "administrative_area": "administrative_area",
        "latitude": "latitude",
        "longitude": "longitude",
        "source": "source",
        "dataset_id": "source_dataset_id",
        "external_id": "external_id",
    }
    for source_field, model_field in field_map.items():
        if source_field in changes:
            value = changes[source_field]
            setattr(item, model_field, value.strip() if isinstance(value, str) else value)
    if payload.tags is not None:
        tags = list(dict.fromkeys(tag.strip() for tag in payload.tags if tag.strip()))
        known_tags = set(
            (
                await session.scalars(
                    select(ObjectTagDefinition.code).where(ObjectTagDefinition.code.in_(tags))
                )
            ).all()
        )
        unknown_tags = [tag for tag in tags if tag not in known_tags]
        if unknown_tags:
            raise HTTPException(
                status_code=422,
                detail=f"Неизвестные теги: {', '.join(unknown_tags)}",
            )
        item.tags.clear()
        item.tags.extend(ObjectTag(tag=tag) for tag in tags)
    if payload.attributes is not None:
        existing = {attribute.attribute_code: attribute for attribute in item.attributes}
        requested_codes: set[str] = set()
        for code in payload.attributes:
            normalized_code = code.strip()
            if normalized_code != code or not normalized_code or len(normalized_code) > 120:
                raise HTTPException(status_code=422, detail="Некорректный код атрибута")
            requested_codes.add(normalized_code)
        for attribute in list(item.attributes):
            if attribute.attribute_code not in requested_codes:
                item.attributes.remove(attribute)
        for code, value in payload.attributes.items():
            serialized, value_type = _serialize_object_attribute(value)
            attribute = existing.get(code)
            if attribute is None:
                attribute = ObjectAttribute(attribute_code=code)
                item.attributes.append(attribute)
            attribute.value = serialized
            attribute.value_type = value_type
    item.updated_at = datetime.now(UTC)
    await session.flush()
    after = _registry_object_read(item).model_dump(mode="json")
    session.add(_audit(admin, "REGISTRY_OBJECT_UPDATED", "CITY_OBJECT", item.id, before, after))
    try:
        await session.commit()
    except IntegrityError as cause:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Объект с такими источником и external ID уже существует"
        ) from cause
    return _registry_object_read(item)


@router.get("/object-types", response_model=list[ObjectTypeRead])
async def object_types(session: Database) -> list[ObjectType]:
    return list((await session.scalars(select(ObjectType).order_by(ObjectType.code))).all())


@router.post("/object-types", response_model=ObjectTypeRead, status_code=201)
async def create_object_type(
    payload: ObjectTypeWrite, session: Database, admin: Admin
) -> ObjectType:
    if await session.scalar(select(ObjectType.id).where(ObjectType.code == payload.code)):
        raise HTTPException(status_code=409, detail="Тип объекта с таким кодом уже существует")
    if payload.parent_id is not None:
        await _one_or_404(session, ObjectType, payload.parent_id)
    item = ObjectType(**payload.model_dump(), source="ADMIN")
    session.add(item)
    await session.flush()
    session.add(
        _audit(
            admin,
            "OBJECT_TYPE_CREATED",
            "OBJECT_TYPE",
            item.id,
            after=payload.model_dump(mode="json"),
        )
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.patch("/object-types/{object_type_id}", response_model=ObjectTypeRead)
async def update_object_type(
    object_type_id: int, payload: ObjectTypeUpdate, session: Database, admin: Admin
) -> ObjectType:
    item: ObjectType = await _one_or_404(session, ObjectType, object_type_id)
    before = {
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "parent_id": item.parent_id,
        "is_active": item.is_active,
    }
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes:
        duplicate_code = await session.scalar(
            select(ObjectType.id).where(
                ObjectType.code == changes["code"], ObjectType.id != item.id
            )
        )
        if duplicate_code:
            raise HTTPException(status_code=409, detail="Тип объекта с таким кодом уже существует")
    if changes.get("parent_id") == item.id:
        raise HTTPException(
            status_code=422, detail="Тип объекта не может быть родителем самому себе"
        )
    if "parent_id" in changes and changes["parent_id"] is not None:
        await _one_or_404(session, ObjectType, changes["parent_id"])
    for key, value in changes.items():
        setattr(item, key, value)
    after = {
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "parent_id": item.parent_id,
        "is_active": item.is_active,
    }
    session.add(_audit(admin, "OBJECT_TYPE_UPDATED", "OBJECT_TYPE", item.id, before, after))
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/imports", response_model=list[ImportRunRead])
async def imports(session: Database) -> list[ImportRun]:
    return list(
        (
            await session.scalars(
                select(ImportRun).order_by(ImportRun.started_at.desc()).limit(100)
            )
        ).all()
    )


@router.get("/imports/catalog")
async def import_catalog(session: Database) -> list[dict[str, Any]]:
    counts = {
        "classifier": int(
            (await session.scalar(select(func.count()).select_from(IncidentClassifierRule))) or 0
        ),
        "services": int(
            (await session.scalar(select(func.count()).select_from(DispatchService))) or 0
        ),
        "objects": int((await session.scalar(select(func.count()).select_from(CityObject))) or 0),
    }
    runs = list(
        (await session.scalars(select(ImportRun).order_by(ImportRun.started_at.desc()))).all()
    )
    latest: dict[str, ImportRun] = {}
    for run in runs:
        latest.setdefault(run.source, run)
    return [
        {
            "key": key,
            **metadata,
            "record_count": counts[key],
            "last_import": (
                ImportRunRead.model_validate(latest[key]).model_dump(mode="json")
                if key in latest
                else None
            ),
        }
        for key, metadata in IMPORT_DATASETS.items()
    ]


@router.get("/imports/{source}/export")
async def export_import_dataset(source: str, session: Database) -> dict[str, Any]:
    dataset = _dataset_or_404(source)
    return await export_dataset(session, dataset)


@router.post("/imports/{source}/run", response_model=ImportRunRead)
async def run_import(
    source: str,
    payload: ImportEnvelope,
    session: Database,
    admin: Admin,
) -> ImportRun:
    dataset = _dataset_or_404(source)
    if payload.dataset != dataset:
        raise HTTPException(
            status_code=422,
            detail="Выбранный раздел не совпадает с набором данных в файле",
        )
    dataset_id = payload.dataset_id or payload.file_name
    run = ImportRun(
        source=dataset,
        dataset_id=dataset_id,
        status="RUNNING",
        details={"file_name": payload.file_name},
    )
    session.add(run)
    try:
        stats = await import_dataset(session, dataset, payload.records)
        run.status = "SUCCESS"
        run.received = stats["received"]
        run.created = stats["created"]
        run.updated = stats["updated"]
        run.skipped = stats["skipped"]
        run.details = {
            "file_name": payload.file_name,
            "format": payload.format,
            "version": payload.version,
            **stats.get("details", {}),
        }
        run.finished_at = datetime.now(UTC)
        await session.flush()
        session.add(
            _audit(
                admin,
                "DATA_IMPORTED",
                "REFERENCE_DATA",
                dataset,
                after={
                    "dataset_id": dataset_id,
                    "received": run.received,
                    "created": run.created,
                    "updated": run.updated,
                    "skipped": run.skipped,
                },
            )
        )
        await session.commit()
        await session.refresh(run)
        return run
    except (ValueError, IntegrityError) as exc:
        await session.rollback()
        failed = ImportRun(
            source=dataset,
            dataset_id=dataset_id,
            status="FAILED",
            errors=1,
            details={"file_name": payload.file_name, "error": str(exc)},
            finished_at=datetime.now(UTC),
        )
        session.add(failed)
        await session.commit()
        raise HTTPException(status_code=422, detail=f"Файл не импортирован: {exc}") from exc


@router.get("/data-quality", response_model=list[DataQualityRead])
async def data_quality(session: Database, status_filter: str = "OPEN") -> list[DataQualityIssue]:
    statement = select(DataQualityIssue)
    if status_filter:
        statement = statement.where(DataQualityIssue.status == status_filter)
    return list(
        (
            await session.scalars(statement.order_by(DataQualityIssue.created_at.desc()).limit(200))
        ).all()
    )


def _ai_from_environment() -> AIProviderConfig:
    settings = get_settings()
    return AIProviderConfig(
        id=1,
        provider=settings.ai_text_provider.upper(),
        model=settings.ai_text_model,
        base_url=settings.ai_text_base_url or "https://api.openai.com/v1",
        enabled=settings.ai_text_enabled,
        timeout_seconds=int(settings.ai_text_timeout_seconds),
    )


async def _ai_config(session: AsyncSession) -> AIProviderConfig:
    config = await session.get(AIProviderConfig, 1)
    if config is None:
        config = _ai_from_environment()
        session.add(config)
        await session.flush()
    return config


def _ai_read(config: AIProviderConfig) -> AIConfigRead:
    return AIConfigRead(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        enabled=config.enabled,
        timeout_seconds=config.timeout_seconds,
        api_key_configured=_ai_api_key_configured(config),
        updated_at=config.updated_at,
    )


def _environment_ai_api_key() -> str:
    settings = get_settings()
    return settings.ai_text_api_key or settings.openai_api_key


def _ai_api_key_configured(config: AIProviderConfig | None) -> bool:
    return bool(config and config.api_key_encrypted) or bool(_environment_ai_api_key())


def _effective_ai_api_key(config: AIProviderConfig | None, supplied: str | None = None) -> str:
    if supplied:
        return supplied
    if config is not None and config.api_key_encrypted:
        return decrypt_api_key(config.api_key_encrypted)
    return _environment_ai_api_key()


def _ai_configuration_present(config: AIProviderConfig) -> bool:
    if config.provider.lower() == "template":
        return True
    if not config.model:
        return False
    if (
        config.provider.lower() == "openai"
        or config.base_url.rstrip("/") == "https://api.openai.com/v1"
    ):
        return _ai_api_key_configured(config)
    return bool(config.base_url)


def _validate_ai_endpoint(provider: str, base_url: str) -> str:
    normalized_provider = provider.lower()
    if normalized_provider not in {"openai", "openai_compatible", "template"}:
        raise HTTPException(status_code=422, detail="Неизвестный AI provider")
    url = urlsplit(base_url)
    if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
        raise HTTPException(status_code=422, detail="Некорректный AI endpoint")
    if normalized_provider == "openai" and base_url.rstrip("/") != "https://api.openai.com/v1":
        raise HTTPException(status_code=422, detail="Для OpenAI используйте официальный endpoint")
    return normalized_provider


@router.get("/ai", response_model=AIConfigRead)
async def get_ai(session: Database) -> AIConfigRead:
    config = await session.get(AIProviderConfig, 1) or _ai_from_environment()
    return _ai_read(config)


@router.put("/ai", response_model=AIConfigRead)
async def update_ai(payload: AIConfigUpdate, session: Database, admin: Admin) -> AIConfigRead:
    _validate_ai_endpoint(payload.provider, payload.base_url)
    if payload.enabled and payload.provider.lower() != "template" and not payload.model.strip():
        raise HTTPException(status_code=422, detail="Укажите модель AI")
    config = await _ai_config(session)
    before = _ai_read(config).model_dump(mode="json")
    for key, value in payload.model_dump().items():
        setattr(config, key, value)
    if payload.api_key:
        config.api_key_encrypted = encrypt_api_key(payload.api_key)
    config.updated_at = datetime.now(UTC)
    after = _ai_read(config).model_dump(mode="json")
    session.add(_audit(admin, "AI_CONFIG_UPDATED", "AI_PROVIDER", config.id, before, after))
    await session.commit()
    return _ai_read(config)


@router.post("/ai/models", response_model=AIModelCatalogRead)
async def ai_models(payload: AIModelCatalogRequest, session: Database) -> AIModelCatalogRead:
    provider_name = _validate_ai_endpoint(payload.provider, payload.base_url)
    if provider_name == "template":
        return AIModelCatalogRead(models=[])
    stored = await session.get(AIProviderConfig, 1)
    api_key = _effective_ai_api_key(stored, payload.api_key)
    if provider_name == "openai":
        provider = OpenAIProvider(model="", api_key=api_key)
    else:
        provider = OpenAICompatibleProvider(
            base_url=payload.base_url,
            model="",
            api_key=api_key,
        )
    try:
        return AIModelCatalogRead(models=await provider.list_models())
    except (httpx.HTTPError, ValueError) as cause:
        raise HTTPException(
            status_code=502,
            detail="Не удалось получить список моделей от AI provider",
        ) from cause


@router.post("/ai/health")
async def ai_health(session: Database) -> dict[str, Any]:
    config = await session.get(AIProviderConfig, 1) or _ai_from_environment()
    provider_name = _validate_ai_endpoint(config.provider, config.base_url)
    api_key = _effective_ai_api_key(config)
    if provider_name == "template":
        provider = TemplateTextGenerationProvider()
    elif provider_name == "openai":
        provider = OpenAIProvider(model=config.model, api_key=api_key)
    else:
        provider = OpenAICompatibleProvider(
            base_url=config.base_url,
            model=config.model,
            api_key=api_key,
        )
    health = await provider.healthcheck()
    return {
        "status": health.status,
        "available": health.status == "AVAILABLE",
        "provider": health.provider,
        "model": health.model,
        "renderer_enabled": config.enabled,
    }


@router.get("/ai/usage", response_model=list[AIUsageRead])
async def ai_usage(session: Database) -> list[AIUsageDaily]:
    return list(
        (
            await session.scalars(select(AIUsageDaily).order_by(AIUsageDaily.day.desc()).limit(31))
        ).all()
    )


@router.get("/scenarios", response_model=list[ScenarioAdminRead])
async def scenarios(session: Database) -> list[ScenarioAdminRead]:
    rows = (
        await session.execute(
            select(ScenarioTemplate, User)
            .join(User, User.id == ScenarioTemplate.created_by_user_id)
            .options(selectinload(ScenarioTemplate.classifier_rule))
            .order_by(ScenarioTemplate.updated_at.desc())
        )
    ).all()
    return [
        ScenarioAdminRead(
            id=scenario.id,
            title=scenario.name,
            author_id=author.id,
            author=author.full_name,
            status=scenario.status,
            difficulty=scenario.difficulty,
            incident_type=(
                scenario.classifier_rule.final_incident_type
                if scenario.classifier_rule is not None
                else None
            ),
            updated_at=scenario.updated_at,
            archived=scenario.status == "ARCHIVED",
        )
        for scenario, author in rows
    ]


@router.post("/scenarios/{scenario_id}/archive", status_code=204)
async def archive_scenario(scenario_id: int, session: Database, admin: Admin) -> None:
    scenario: ScenarioTemplate = await _one_or_404(session, ScenarioTemplate, scenario_id)
    before = {"status": scenario.status}
    scenario.status = "ARCHIVED"
    scenario.archived_at = datetime.now(UTC)
    scenario.updated_at = scenario.archived_at
    session.add(
        _audit(
            admin,
            "SCENARIO_ARCHIVED",
            "SCENARIO_TEMPLATE",
            scenario.id,
            before,
            {"status": "ARCHIVED"},
        )
    )
    await session.commit()


@router.post("/scenarios/{scenario_id}/restore", status_code=204)
async def restore_scenario(scenario_id: int, session: Database, admin: Admin) -> None:
    scenario: ScenarioTemplate = await _one_or_404(session, ScenarioTemplate, scenario_id)
    before = {"status": scenario.status}
    scenario.status = "READY"
    scenario.archived_at = None
    scenario.updated_at = datetime.now(UTC)
    session.add(
        _audit(
            admin,
            "SCENARIO_RESTORED",
            "TRAINING_SCENARIO",
            scenario.id,
            before,
            {"status": "READY"},
        )
    )
    await session.commit()


@router.get("/audit", response_model=list[AuditRead])
async def audit(
    session: Database, limit: int = Query(default=200, ge=1, le=500)
) -> list[AdminAudit]:
    return list(
        (
            await session.scalars(
                select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(limit)
            )
        ).all()
    )


@router.get("/system")
async def system(session: Database) -> dict[str, Any]:
    await session.execute(text("SELECT 1"))
    db_revisions = (
        await session.scalars(text("SELECT version_num FROM alembic_version ORDER BY version_num"))
    ).all()
    ai_config = await session.get(AIProviderConfig, 1) or _ai_from_environment()
    ai_status = "DISABLED"
    if ai_config.enabled:
        ai_status = "CONFIGURED" if _ai_configuration_present(ai_config) else "ERROR"
    return {
        "services": {
            "backend": "OK",
            "postgresql": "OK",
            "ai_provider": ai_status,
            "scenario_engine": "OK",
            "realtime": "OK",
        },
        "version": "0.1.0",
        "git_commit": getenv("APP_GIT_COMMIT", "unknown"),
        "db_revision": ", ".join(db_revisions) if db_revisions else "unknown",
        "environment": getenv("APP_ENVIRONMENT", "development"),
        "server_time": datetime.now(UTC),
    }
