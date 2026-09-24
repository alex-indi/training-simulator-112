"""Генерация seed и повторяемая загрузка московских объектов.

Запуск из backend:
    uv run python -m scripts.import_city_objects.import_objects build
    uv run python -m scripts.import_city_objects.import_objects load
"""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.modules.object_registry.models import CityObject, ObjectAttribute, ObjectTag, ObjectType
from scripts.import_city_objects.mappers.education import map_education
from scripts.import_city_objects.mappers.metro import map_metro
from seed.import_object_types import load_object_types, upsert_object_types

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "seed/object_registry/source_data"
SEED_DIR = ROOT / "seed/city_objects"
MANAGED_TAGS = {"education", "children", "mass_people", "transport", "underground"}
MANAGED_ATTRIBUTES = {
    "institution_type",
    "institution_subtype",
    "department",
    "needs_review",
    "station_name",
    "has_underground_area",
    "entrance_count",
    "source_entrance_ids",
    "lines",
    "districts",
    "administrative_areas",
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_seed() -> dict:
    education_rows = _json(SOURCE_DIR / "schools_raw_rows.json")
    metro_rows = _json(SOURCE_DIR / "metro_raw_rows.json")
    education = [map_education(row) for row in education_rows]
    metro, metro_quality = map_metro(metro_rows)
    objects = sorted(education + metro, key=lambda row: (row["source"], row["external_id"]))
    keys = [(row["source"], row["external_id"]) for row in objects]
    if len(keys) != len(set(keys)):
        raise ValueError("Повторяющийся source/external_id в исходных данных")
    known_types = {row["code"] for row in load_object_types()}
    if any(row["object_type_code"] not in known_types for row in objects):
        raise ValueError("Seed содержит неизвестный тип объекта")
    attributes = [
        {
            "source": row["source"],
            "external_id": row["external_id"],
            "attribute_code": code,
            "value": json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(value, (bool, list, dict))
            else str(value),
            "value_type": "boolean"
            if isinstance(value, bool)
            else "json"
            if isinstance(value, (list, dict))
            else "integer"
            if isinstance(value, int)
            else "text",
        }
        for row in objects
        for code, value in sorted(row["attributes"].items())
        if value is not None and value != ""
    ]
    tags = [
        {"source": row["source"], "external_id": row["external_id"], "tag": tag}
        for row in objects
        for tag in sorted(set(row["tags"]))
    ]
    city_objects = [
        {k: v for k, v in row.items() if k not in ("attributes", "tags")} for row in objects
    ]
    _write(SEED_DIR / "city_objects.json", city_objects)
    _write(SEED_DIR / "object_attributes.json", attributes)
    _write(SEED_DIR / "object_tags.json", tags)
    counts = Counter(row["object_type_code"] for row in objects)
    report = {
        "source_rows": {"747": len(education_rows), "624": len(metro_rows)},
        "imported": dict(sorted(counts.items())),
        "metro": metro_quality,
        "education_missing_coordinates": sum(row["latitude"] is None for row in education),
        "education_unknown_type": counts["EDUCATION_UNKNOWN"],
        "duplicate_object_keys": 0,
        "seed_objects": len(objects),
        "seed_attributes": len(attributes),
        "seed_tags": len(tags),
    }
    _write(SEED_DIR / "object_import_report.json", report)
    return report


def _validate_seed(objects: list[dict], attributes: list[dict], tags: list[dict]) -> None:
    keys = set()
    for row in objects:
        key = (row.get("source"), row.get("external_id"))
        if not all(key) or not row.get("source_dataset_id") or not row.get("object_type_code"):
            raise ValueError(f"Недостаточно данных источника для объекта: {key}")
        if key in keys:
            raise ValueError(f"Дубликат объекта: {key}")
        keys.add(key)
    for collection in (attributes, tags):
        for row in collection:
            if (row["source"], row["external_id"]) not in keys:
                raise ValueError("Атрибут/тег ссылается на отсутствующий объект")


def upsert_objects(
    session: Session, objects: list[dict], attributes: list[dict], tags: list[dict]
) -> None:
    """Обновляет исходные поля; пользовательские атрибуты и теги сохраняет."""
    _validate_seed(objects, attributes, tags)
    type_ids = dict(session.execute(select(ObjectType.code, ObjectType.id)).all())
    missing_types = {row["object_type_code"] for row in objects} - type_ids.keys()
    if missing_types:
        raise ValueError(f"Отсутствуют ObjectType: {', '.join(sorted(missing_types))}")
    keys = {(row["source"], row["external_id"]) for row in objects}
    existing = {
        (item.source, item.external_id): item
        for item in session.scalars(
            select(CityObject).where(CityObject.source.in_({key[0] for key in keys}))
        )
    }
    for row in objects:
        key = (row["source"], row["external_id"])
        item = existing.get(key)
        if item is None:
            item = CityObject(source=row["source"], external_id=row["external_id"])
            session.add(item)
            existing[key] = item
        for field in (
            "name",
            "address",
            "district",
            "administrative_area",
            "latitude",
            "longitude",
            "source_dataset_id",
        ):
            setattr(item, field, row[field])
        item.object_type_id = type_ids[row["object_type_code"]]
    session.flush()
    object_ids = {key: existing[key].id for key in keys}
    existing_attributes = {
        (row.object_id, row.attribute_code): row
        for row in session.scalars(
            select(ObjectAttribute).where(ObjectAttribute.object_id.in_(object_ids.values()))
        )
    }
    for row in attributes:
        key = (object_ids[(row["source"], row["external_id"])], row["attribute_code"])
        item = existing_attributes.get(key)
        if item is None:
            item = ObjectAttribute(object_id=key[0], attribute_code=key[1])
            session.add(item)
            existing_attributes[key] = item
        item.value = row["value"]
        item.value_type = row["value_type"]
    desired_attributes = {
        (object_ids[(row["source"], row["external_id"])], row["attribute_code"])
        for row in attributes
    }
    for key, item in existing_attributes.items():
        if key[1] in MANAGED_ATTRIBUTES and key not in desired_attributes:
            session.delete(item)
    existing_tag_rows = list(
        session.scalars(select(ObjectTag).where(ObjectTag.object_id.in_(object_ids.values())))
    )
    existing_tags = {(row.object_id, row.tag) for row in existing_tag_rows}
    desired_tags = {(object_ids[(row["source"], row["external_id"])], row["tag"]) for row in tags}
    for item in existing_tag_rows:
        if item.tag in MANAGED_TAGS and (item.object_id, item.tag) not in desired_tags:
            session.delete(item)
    for row in tags:
        key = (object_ids[(row["source"], row["external_id"])], row["tag"])
        if key not in existing_tags:
            session.add(ObjectTag(object_id=key[0], tag=key[1]))
            existing_tags.add(key)
    session.flush()


async def load_seed() -> None:
    objects = _json(SEED_DIR / "city_objects.json")
    attributes = _json(SEED_DIR / "object_attributes.json")
    tags = _json(SEED_DIR / "object_tags.json")
    _validate_seed(objects, attributes, tags)
    engine = create_database_engine(get_settings())
    factory = create_session_factory(engine)
    try:
        async with factory.begin() as session:
            await upsert_object_types(session, load_object_types())
            await session.run_sync(upsert_objects, objects, attributes, tags)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "load"))
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build_seed(), ensure_ascii=False, indent=2))
    else:
        asyncio.run(load_seed())


if __name__ == "__main__":
    main()
