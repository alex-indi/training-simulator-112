"""Проверки маппинга исходных наборов и повторной загрузки реестра."""

import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.object_registry.models import CityObject, ObjectAttribute, ObjectTag, ObjectType
from scripts.import_city_objects.import_objects import SEED_DIR, build_seed, upsert_objects
from scripts.import_city_objects.mappers.education import classify, map_education
from scripts.import_city_objects.mappers.metro import map_metro
from seed.import_object_types import load_object_types


def test_education_classification_preserves_unknown() -> None:
    assert classify("Дошкольное образовательное учреждение", "Детский сад") == (
        "KINDERGARTEN",
        False,
    )
    assert classify("Общеобразовательное учреждение", "Средняя школа") == ("SCHOOL", False)
    assert classify("Дошкольное учреждение", "Начальная школа – детский сад") == (
        "EDUCATIONAL_COMPLEX",
        False,
    )
    assert classify("Структура управления образования", "Дирекция") == ("EDUCATION_UNKNOWN", True)
    row = {
        "global_id": 11,
        "Cells": {
            "poln_name": "\u00a0Детский сад № 1",
            "tipe_uchrezhden": "Дошкольное образовательное учреждение",
            "vid_uchrezhdeniya": "Детский сад",
            "yuridich_adress": "Москва, ул. Тестовая, д. 1",
        },
    }
    mapped = map_education(row)
    assert mapped["name"] == "Детский сад № 1"
    assert mapped["external_id"] == "11"
    assert mapped["source_dataset_id"] == "747"
    assert mapped["tags"] == ["education", "children", "mass_people"]


def test_metro_aggregation_keeps_source_ids_and_excludes_outside() -> None:
    def entrance(global_id: int, territory: str, latitude: str) -> dict:
        return {
            "global_id": global_id,
            "Cells": {
                "NameOfStation": "Тестовая",
                "OnTerritoryOfMoscow": territory,
                "Latitude_WGS84": latitude,
                "Longitude_WGS84": "37.5",
                "District": "Тестовый район",
                "AdmArea": "Тестовый округ",
                "Line": "Тестовая линия",
                "VestibuleType": "подземный",
            },
        }

    objects, report = map_metro(
        [entrance(1, "да", "55.5"), entrance(2, "да", "55.7"), entrance(3, "нет", "55.9")]
    )
    assert len(objects) == 1
    station = objects[0]
    assert station["external_id"] == "station:Тестовая"
    assert station["latitude"] == "55.6"
    assert station["attributes"]["source_entrance_ids"] == ["1", "2"]
    assert station["attributes"]["entrance_count"] == 2
    assert report["outside_moscow_entrances"] == 1


def test_seed_is_deterministic_and_valid() -> None:
    first = build_seed()
    before = {path.name: path.read_bytes() for path in SEED_DIR.glob("*.json")}
    second = build_seed()
    after = {path.name: path.read_bytes() for path in SEED_DIR.glob("*.json")}
    assert first == second
    assert before == after
    assert first["seed_objects"] == first["source_rows"]["747"] + first["metro"]["station_count"]
    objects = json.loads((SEED_DIR / "city_objects.json").read_text())
    assert all(row["source"] and row["source_dataset_id"] and row["external_id"] for row in objects)


def test_upsert_updates_without_duplicates() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            ObjectType.__table__,
            CityObject.__table__,
            ObjectAttribute.__table__,
            ObjectTag.__table__,
        ],
    )
    with Session(engine) as session:
        types = {}
        for row in load_object_types():
            item = ObjectType(
                code=row["code"],
                name=row["name"],
                source=row["source"],
                parent=types.get(row["parent_code"]),
            )
            session.add(item)
            session.flush()
            types[item.code] = item
        objects = [
            {
                "source": "data.mos.ru:747",
                "source_dataset_id": "747",
                "external_id": "1",
                "name": "Исходное название",
                "object_type_code": "SCHOOL",
                "address": "Москва",
                "district": None,
                "administrative_area": None,
                "latitude": None,
                "longitude": None,
            }
        ]
        attributes = [
            {
                "source": "data.mos.ru:747",
                "external_id": "1",
                "attribute_code": "institution_type",
                "value": "Школа",
                "value_type": "text",
            }
        ]
        tags = [{"source": "data.mos.ru:747", "external_id": "1", "tag": "education"}]
        upsert_objects(session, objects, attributes, tags)
        first_id = session.scalar(select(CityObject.id))
        objects[0]["name"] = "Обновлённое название"
        attributes[0]["value"] = "Общеобразовательная школа"
        upsert_objects(session, objects, attributes, tags)
        assert session.scalar(select(func.count()).select_from(CityObject)) == 1
        assert session.scalar(select(func.count()).select_from(ObjectAttribute)) == 1
        assert session.scalar(select(func.count()).select_from(ObjectTag)) == 1
        assert session.scalar(select(CityObject.id)) == first_id
        assert session.scalar(select(CityObject.name)) == "Обновлённое название"
        assert session.scalar(select(ObjectAttribute.value)) == "Общеобразовательная школа"
        session.add(ObjectTag(object_id=first_id, tag="custom"))
        upsert_objects(session, objects, [], [])
        assert session.scalars(select(ObjectTag.tag)).all() == ["custom"]
        assert session.scalar(select(func.count()).select_from(ObjectAttribute)) == 0
    engine.dispose()
