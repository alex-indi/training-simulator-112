"""Versioned JSON exchange for administrator-managed reference data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

EXCHANGE_FORMAT = "ut112-admin-data"
EXCHANGE_VERSION = 1
DatasetKey = Literal["classifier", "services", "objects"]


class ImportEnvelope(BaseModel):
    format: Literal["ut112-admin-data"]
    version: Literal[1]
    dataset: DatasetKey
    dataset_id: str | None = Field(default=None, max_length=120)
    exported_at: datetime | None = None
    file_name: str | None = Field(default=None, max_length=255)
    records: Any


class ServiceRecord(BaseModel):
    source_reference: str = Field(min_length=1, max_length=500)
    official_name: str = Field(min_length=1, max_length=2000)
    organization: str | None = Field(default=None, max_length=4000)
    service_level: str | None = Field(default=None, max_length=120)


class FeatureRecord(BaseModel):
    level: str = Field(min_length=1, max_length=80)
    source_column: str = Field(min_length=1, max_length=160)
    source_value: str = Field(min_length=1, max_length=2000)
    name: str = Field(min_length=1, max_length=2000)


class RuleServiceRecord(BaseModel):
    service_source_reference: str = Field(min_length=1, max_length=500)
    source_reference: str = Field(min_length=1, max_length=500)


class ClassifierRuleRecord(BaseModel):
    source_reference: str = Field(min_length=1, max_length=500)
    source_code: str | None = Field(default=None, max_length=160)
    incident_group: str = Field(min_length=1, max_length=2000)
    final_incident_type: str = Field(min_length=1, max_length=2000)
    ekp35_type: str | None = Field(default=None, max_length=2000)
    features: list[FeatureRecord] = Field(default_factory=list)
    services: list[RuleServiceRecord] = Field(default_factory=list)


class ObjectTypeRecord(BaseModel):
    code: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=250)
    parent_code: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    source: str = Field(min_length=1, max_length=250)
    is_active: bool = True


class TagDefinitionRecord(BaseModel):
    code: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=250)
    description: str | None = Field(default=None, max_length=4000)


class CityObjectRecord(BaseModel):
    source: str = Field(min_length=1, max_length=250)
    external_id: str = Field(min_length=1, max_length=250)
    name: str = Field(min_length=1, max_length=500)
    object_type_code: str = Field(min_length=1, max_length=120)
    address: str | None = None
    district: str | None = Field(default=None, max_length=250)
    administrative_area: str | None = Field(default=None, max_length=250)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source_dataset_id: str | None = Field(default=None, max_length=250)
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @field_validator("attributes")
    @classmethod
    def _validate_attribute_codes(cls, value: dict[str, Any]) -> dict[str, Any]:
        invalid = [code for code in value if not code or len(code) > 120]
        if invalid:
            raise ValueError("Код атрибута должен содержать от 1 до 120 символов")
        return value


class ObjectBundle(BaseModel):
    object_types: list[ObjectTypeRecord]
    tag_definitions: list[TagDefinitionRecord]
    objects: list[CityObjectRecord]


def _attribute_value(row: ObjectAttribute) -> Any:
    if row.value_type == "integer":
        return int(row.value)
    if row.value_type == "boolean":
        return row.value.lower() in {"1", "true", "yes"}
    if row.value_type == "json":
        return json.loads(row.value)
    return row.value


def _serialize_attribute(value: Any) -> tuple[str, str]:
    if isinstance(value, bool):
        return ("true" if value else "false"), "boolean"
    if isinstance(value, int):
        return str(value), "integer"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True), "json"
    if value is None:
        return "", "text"
    return str(value), "text"


def _changed(item: object, values: dict[str, Any]) -> bool:
    return any(getattr(item, field) != value for field, value in values.items())


async def export_dataset(session: AsyncSession, dataset: DatasetKey) -> dict[str, Any]:
    if dataset == "services":
        rows = (
            await session.scalars(
                select(DispatchService).order_by(DispatchService.source_reference)
            )
        ).all()
        records: Any = [
            ServiceRecord(
                source_reference=row.source_reference,
                official_name=row.official_name,
                organization=row.organization,
                service_level=row.service_level,
            ).model_dump(mode="json")
            for row in rows
        ]
    elif dataset == "classifier":
        rows = (
            await session.scalars(
                select(IncidentClassifierRule)
                .options(
                    selectinload(IncidentClassifierRule.features).selectinload(
                        IncidentRuleFeature.feature
                    ),
                    selectinload(IncidentClassifierRule.services).selectinload(
                        IncidentRuleService.service
                    ),
                )
                .order_by(IncidentClassifierRule.source_reference)
            )
        ).all()
        records = [
            ClassifierRuleRecord(
                source_reference=row.source_reference,
                source_code=row.source_code,
                incident_group=row.incident_group,
                final_incident_type=row.final_incident_type,
                ekp35_type=row.ekp35_type,
                features=[
                    FeatureRecord(
                        level=link.feature.level,
                        source_column=link.feature.source_column,
                        source_value=link.feature.source_value,
                        name=link.feature.name,
                    )
                    for link in row.features
                ],
                services=[
                    RuleServiceRecord(
                        service_source_reference=link.service.source_reference,
                        source_reference=link.source_reference,
                    )
                    for link in row.services
                ],
            ).model_dump(mode="json")
            for row in rows
        ]
    else:
        types = (await session.scalars(select(ObjectType).order_by(ObjectType.code))).all()
        tags = (
            await session.scalars(select(ObjectTagDefinition).order_by(ObjectTagDefinition.code))
        ).all()
        objects = (
            await session.scalars(
                select(CityObject)
                .options(
                    selectinload(CityObject.object_type),
                    selectinload(CityObject.attributes),
                    selectinload(CityObject.tags),
                )
                .order_by(CityObject.source, CityObject.external_id)
            )
        ).all()
        type_codes = {row.id: row.code for row in types}
        records = ObjectBundle(
            object_types=[
                ObjectTypeRecord(
                    code=row.code,
                    name=row.name,
                    parent_code=type_codes.get(row.parent_id),
                    description=row.description,
                    source=row.source,
                    is_active=row.is_active,
                )
                for row in types
            ],
            tag_definitions=[
                TagDefinitionRecord(code=row.code, name=row.name, description=row.description)
                for row in tags
            ],
            objects=[
                CityObjectRecord(
                    source=row.source,
                    external_id=row.external_id,
                    name=row.name,
                    object_type_code=row.object_type.code,
                    address=row.address,
                    district=row.district,
                    administrative_area=row.administrative_area,
                    latitude=float(row.latitude) if row.latitude is not None else None,
                    longitude=float(row.longitude) if row.longitude is not None else None,
                    source_dataset_id=row.source_dataset_id,
                    attributes={
                        item.attribute_code: _attribute_value(item) for item in row.attributes
                    },
                    tags=sorted(item.tag for item in row.tags),
                )
                for row in objects
            ],
        ).model_dump(mode="json")
    return {
        "format": EXCHANGE_FORMAT,
        "version": EXCHANGE_VERSION,
        "dataset": dataset,
        "dataset_id": f"{dataset}-{datetime.now(UTC).date().isoformat()}",
        "exported_at": datetime.now(UTC).isoformat(),
        "records": records,
    }


async def _import_services(session: AsyncSession, raw: Any) -> dict[str, Any]:
    rows = TypeAdapter(list[ServiceRecord]).validate_python(raw)
    if not rows:
        raise ValueError("Файл не содержит служб")
    if len({row.source_reference for row in rows}) != len(rows):
        raise ValueError("В файле повторяются идентификаторы служб")
    existing = {
        row.source_reference: row for row in (await session.scalars(select(DispatchService))).all()
    }
    created = updated = skipped = 0
    for row in rows:
        values = row.model_dump(exclude={"source_reference"})
        item = existing.get(row.source_reference)
        if item is None:
            item = DispatchService(source_reference=row.source_reference, **values)
            session.add(item)
            existing[row.source_reference] = item
            created += 1
        elif _changed(item, values):
            for field, value in values.items():
                setattr(item, field, value)
            updated += 1
        else:
            skipped += 1
    return {"received": len(rows), "created": created, "updated": updated, "skipped": skipped}


async def _import_classifier(session: AsyncSession, raw: Any) -> dict[str, Any]:
    rows = TypeAdapter(list[ClassifierRuleRecord]).validate_python(raw)
    if not rows:
        raise ValueError("Файл не содержит правил классификатора")
    if len({row.source_reference for row in rows}) != len(rows):
        raise ValueError("В файле повторяются идентификаторы правил")
    rules = {
        row.source_reference: row
        for row in (await session.scalars(select(IncidentClassifierRule))).all()
    }
    features = {
        (row.level, row.source_column, row.source_value): row
        for row in (await session.scalars(select(IncidentFeature))).all()
    }
    services = {
        row.source_reference: row for row in (await session.scalars(select(DispatchService))).all()
    }
    feature_links = {
        (row.rule_id, row.feature_id)
        for row in (await session.scalars(select(IncidentRuleFeature))).all()
    }
    service_links = {
        (row.rule_id, row.service_id): row
        for row in (await session.scalars(select(IncidentRuleService))).all()
    }
    created = updated = skipped = 0
    for row in rows:
        missing = {
            link.service_source_reference
            for link in row.services
            if link.service_source_reference not in services
        }
        if missing:
            raise ValueError(f"Не найдены службы: {', '.join(sorted(missing))}")
        values = {
            "source_code": row.source_code,
            "incident_group": row.incident_group,
            "final_incident_type": row.final_incident_type,
            "ekp35_type": row.ekp35_type,
        }
        item = rules.get(row.source_reference)
        is_created = item is None
        changed = is_created
        if item is None:
            item = IncidentClassifierRule(source_reference=row.source_reference, **values)
            session.add(item)
            rules[row.source_reference] = item
        elif _changed(item, values):
            for field, value in values.items():
                setattr(item, field, value)
            changed = True
        await session.flush()
        for feature in row.features:
            key = (feature.level, feature.source_column, feature.source_value)
            feature_item = features.get(key)
            if feature_item is None:
                feature_item = IncidentFeature(**feature.model_dump())
                session.add(feature_item)
                features[key] = feature_item
                await session.flush()
                changed = True
            elif feature_item.name != feature.name:
                feature_item.name = feature.name
                changed = True
            pair = (item.id, feature_item.id)
            if pair not in feature_links:
                session.add(IncidentRuleFeature(rule_id=item.id, feature_id=feature_item.id))
                feature_links.add(pair)
                changed = True
        for link in row.services:
            service = services[link.service_source_reference]
            pair = (item.id, service.id)
            relation = service_links.get(pair)
            if relation is None:
                relation = IncidentRuleService(
                    rule_id=item.id,
                    service_id=service.id,
                    source_reference=link.source_reference,
                )
                session.add(relation)
                service_links[pair] = relation
                changed = True
            elif relation.source_reference != link.source_reference:
                relation.source_reference = link.source_reference
                changed = True
        if is_created:
            created += 1
        elif changed:
            updated += 1
        else:
            skipped += 1
    return {"received": len(rows), "created": created, "updated": updated, "skipped": skipped}


async def _import_objects(session: AsyncSession, raw: Any) -> dict[str, Any]:
    bundle = ObjectBundle.model_validate(raw)
    if not bundle.objects:
        raise ValueError("Файл не содержит объектов")
    object_keys = [(row.source, row.external_id) for row in bundle.objects]
    if len(object_keys) != len(set(object_keys)):
        raise ValueError("В файле повторяются идентификаторы объектов")
    types = {row.code: row for row in (await session.scalars(select(ObjectType))).all()}
    for row in bundle.object_types:
        item = types.get(row.code)
        if item is None:
            item = ObjectType(code=row.code, name=row.name, source=row.source)
            session.add(item)
            types[row.code] = item
        else:
            item.name = row.name
            item.description = row.description
            item.source = row.source
            item.is_active = row.is_active
    await session.flush()
    for row in bundle.object_types:
        if row.parent_code and row.parent_code not in types:
            raise ValueError(f"Неизвестный родитель типа: {row.parent_code}")
        item = types[row.code]
        item.parent_id = types[row.parent_code].id if row.parent_code else None
        item.description = row.description
        item.is_active = row.is_active
    tag_definitions = {
        row.code: row for row in (await session.scalars(select(ObjectTagDefinition))).all()
    }
    for row in bundle.tag_definitions:
        item = tag_definitions.get(row.code)
        if item is None:
            item = ObjectTagDefinition(code=row.code, name=row.name)
            session.add(item)
            tag_definitions[row.code] = item
        item.name = row.name
        item.description = row.description
    await session.flush()
    objects = {
        (row.source, row.external_id): row
        for row in (await session.scalars(select(CityObject))).all()
    }
    created = updated = skipped = 0
    for row in bundle.objects:
        if row.object_type_code not in types:
            raise ValueError(f"Неизвестный тип объекта: {row.object_type_code}")
        unknown_tags = set(row.tags) - tag_definitions.keys()
        if unknown_tags:
            raise ValueError(f"Неизвестные теги: {', '.join(sorted(unknown_tags))}")
        key = (row.source, row.external_id)
        values = {
            "name": row.name,
            "object_type_id": types[row.object_type_code].id,
            "address": row.address,
            "district": row.district,
            "administrative_area": row.administrative_area,
            "latitude": Decimal(str(row.latitude)) if row.latitude is not None else None,
            "longitude": Decimal(str(row.longitude)) if row.longitude is not None else None,
            "source_dataset_id": row.source_dataset_id,
        }
        item = objects.get(key)
        is_created = item is None
        changed = is_created
        if item is None:
            item = CityObject(source=row.source, external_id=row.external_id, **values)
            session.add(item)
            objects[key] = item
            await session.flush()
        elif _changed(item, values):
            for field, value in values.items():
                setattr(item, field, value)
            changed = True
        attributes = {
            value.attribute_code: value
            for value in (
                await session.scalars(
                    select(ObjectAttribute).where(ObjectAttribute.object_id == item.id)
                )
            ).all()
        }
        for code, value in row.attributes.items():
            serialized, value_type = _serialize_attribute(value)
            attribute = attributes.get(code)
            if attribute is None:
                session.add(
                    ObjectAttribute(
                        object_id=item.id,
                        attribute_code=code,
                        value=serialized,
                        value_type=value_type,
                    )
                )
                changed = True
            elif attribute.value != serialized or attribute.value_type != value_type:
                attribute.value = serialized
                attribute.value_type = value_type
                changed = True
        current_tags = set(
            (
                await session.scalars(select(ObjectTag.tag).where(ObjectTag.object_id == item.id))
            ).all()
        )
        for tag in set(row.tags) - current_tags:
            session.add(ObjectTag(object_id=item.id, tag=tag))
            changed = True
        if changed and not is_created:
            item.updated_at = datetime.now(UTC)
        if is_created:
            created += 1
        elif changed:
            updated += 1
        else:
            skipped += 1
    return {
        "received": len(bundle.objects),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "details": {
            "object_types": len(bundle.object_types),
            "tag_definitions": len(bundle.tag_definitions),
        },
    }


async def import_dataset(
    session: AsyncSession, dataset: DatasetKey, records: Any
) -> dict[str, Any]:
    if dataset == "services":
        return await _import_services(session, records)
    if dataset == "classifier":
        return await _import_classifier(session, records)
    return await _import_objects(session, records)
