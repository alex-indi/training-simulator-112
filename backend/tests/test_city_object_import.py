"""Проверки маппинга исходных наборов и повторной загрузки реестра."""

import json
from contextlib import nullcontext

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.object_registry.address import normalize_address, normalize_generated_text
from app.modules.object_registry.models import (
    CityObject,
    ObjectAttribute,
    ObjectTag,
    ObjectTagDefinition,
    ObjectType,
)
from scripts.import_city_objects import mos_api_client
from scripts.import_city_objects.import_objects import SEED_DIR, build_seed, upsert_objects
from scripts.import_city_objects.mappers.education import classify, map_education
from scripts.import_city_objects.mappers.healthcare import map_healthcare
from scripts.import_city_objects.mappers.metro import map_metro
from seed.import_object_tags import load_object_tags, upsert_object_tags
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
            "yuridich_adress": "123456, г. Москва, ул. Тестовая, д. 1",
        },
    }
    mapped = map_education(row)
    assert mapped["name"] == "Детский сад № 1"
    assert mapped["external_id"] == "11"
    assert mapped["source_dataset_id"] == "747"
    assert mapped["address"] == "г. Москва, ул. Тестовая, д. 1"
    assert mapped["tags"] == ["education", "children", "mass_people"]


def test_city_object_addresses_start_with_locality() -> None:
    assert normalize_address(
        '"127273 г. Москва, ул. Отрадная, д. 5 "Б"', default_city="г. Москва"
    ) == (
        'г. Москва, ул. Отрадная, д. 5 "Б"'
    )
    assert normalize_address("119 454 г.Москва, ул. Лобачевского, д. 56") == (
        "г.Москва, ул. Лобачевского, д. 56"
    )
    assert normalize_address("109012 109012 г. Москва, ул. Пушечная, д. 4") == (
        "г. Москва, ул. Пушечная, д. 4"
    )
    assert normalize_address(
        "125057, Ленинградский проспект, д. 75Д", default_city="г. Москва"
    ) == (
        "г. Москва, Ленинградский проспект, д. 75Д"
    )
    assert normalize_address(
        "Российская Федерация, город Москва, улица Лескова, дом 6"
    ) == "город Москва, улица Лескова, дом 6"
    assert normalize_address("Московская область, г. Пушкино, улица Лермонтовская") == (
        "г. Пушкино, улица Лермонтовская"
    )
    assert normalize_address("0", default_city="г. Москва") is None
    assert normalize_generated_text(
        "Задымление: 117624, г. Москва, ул. Изюмская, д. 35.",
        "117624, г.Москва, ул. Изюмская, д. 35",
        "г.Москва, ул. Изюмская, д. 35",
    ) == "Задымление: г. Москва, ул. Изюмская, д. 35."


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


def test_healthcare_maps_each_address_and_preserves_source_ids() -> None:
    row = {
        "global_id": 42,
        "Cells": {
            "FullName": "Больница",
            "Category": "Больница взрослая",
            "CloseFlag": "действует",
            "ObjectAddress": [
                {
                    "global_id": 7,
                    "Address": "Российская Федерация, город Москва, дом 1",
                    "District": "Район 1",
                },
                {"global_id": 8, "Address": "Москва, дом 2", "District": "Район 2"},
            ],
            "WorkingHours": [{"DayWeek": day, "WorkHours": "круглосуточно"} for day in range(7)],
        },
    }
    objects, quality = map_healthcare([row], 517, "HOSPITAL")
    assert [item["external_id"] for item in objects] == ["42:7", "42:8"]
    assert [item["district"] for item in objects] == ["Район 1", "Район 2"]
    assert objects[0]["address"] == "город Москва, дом 1"
    assert objects[0]["source"] == "data.mos.ru:517"
    assert objects[0]["source_dataset_id"] == "517"
    assert objects[0]["attributes"]["source_row_id"] == "42"
    assert objects[0]["attributes"]["source_address_id"] == "7"
    assert objects[0]["tags"] == ["medical", "patients", "mass_people", "24_hours"]
    assert quality["objects"] == 2
    assert quality["missing_coordinates"] == 2


def test_seed_is_deterministic_and_valid() -> None:
    first = build_seed()
    before = {path.name: path.read_bytes() for path in SEED_DIR.glob("*.json")}
    second = build_seed()
    after = {path.name: path.read_bytes() for path in SEED_DIR.glob("*.json")}
    assert first == second
    assert before == after
    assert first["seed_objects"] == (
        first["source_rows"]["747"]
        + first["metro"]["station_count"]
        + sum(item["objects"] for item in first["healthcare"].values())
    )
    objects = json.loads((SEED_DIR / "city_objects.json").read_text(encoding="utf-8"))
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
            ObjectTagDefinition.__table__,
            ObjectTag.__table__,
        ],
    )
    with Session(engine) as session:
        upsert_object_tags(session, load_object_tags())
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
        session.add(ObjectTagDefinition(code="custom", name="Пользовательский"))
        session.add(ObjectTag(object_id=first_id, tag="custom"))
        session.flush()
        upsert_objects(session, objects, [], [])
        assert set(session.scalars(select(ObjectTag.tag)).all()) == {"custom", "education"}
        assert session.scalar(select(func.count()).select_from(ObjectAttribute)) == 1
    engine.dispose()


def test_upsert_rejects_unknown_tag() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[
            ObjectType.__table__,
            CityObject.__table__,
            ObjectAttribute.__table__,
            ObjectTagDefinition.__table__,
            ObjectTag.__table__,
        ],
    )
    with Session(engine) as session:
        session.add(ObjectType(code="BUILDING", name="Здание", source="test"))
        session.flush()
        with pytest.raises(ValueError, match="Отсутствуют теги в справочнике: unknown"):
            upsert_objects(
                session,
                [
                    {
                        "source": "test",
                        "external_id": "1",
                        "source_dataset_id": "test",
                        "object_type_code": "BUILDING",
                    }
                ],
                [],
                [{"source": "test", "external_id": "1", "tag": "unknown"}],
            )
    engine.dispose()


def test_manual_dataset_fetch_keeps_source_and_refuses_overwrite(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mos_api_client, "get_api_key", lambda: "test-key")
    calls = []

    def fake_api_get(path, *, api_key, timeout, params=None, session=None):
        calls.append((path, api_key, timeout, params))
        return {"Id": 1234, "Caption": "Hospitals"}

    def fake_get_rows(dataset_id, *, api_key, limit, timeout):
        assert (dataset_id, api_key, limit, timeout) == (1234, "test-key", 2, (5, 11))
        return [{"global_id": 1, "Cells": {"Name": "Тестовая больница"}}]

    monkeypatch.setattr(mos_api_client, "api_get", fake_api_get)
    monkeypatch.setattr(mos_api_client, "get_rows", fake_get_rows)
    monkeypatch.setattr(mos_api_client, "make_session", lambda: nullcontext(object()))
    report = mos_api_client.fetch_dataset(
        1234,
        "hospitals",
        output_dir=tmp_path,
        page_size=2,
        connect_timeout=5,
        read_timeout=11,
    )
    assert report == {
        "source": "data.mos.ru",
        "dataset_id": 1234,
        "name": "hospitals",
        "rows": 1,
        "caption": "Hospitals",
    }
    assert json.loads((tmp_path / "hospitals_dataset_info.json").read_text(encoding="utf-8")) == {
        "Id": 1234,
        "Caption": "Hospitals",
    }
    rows = json.loads((tmp_path / "hospitals_raw_rows.json").read_text(encoding="utf-8"))
    assert rows[0]["global_id"] == 1
    assert calls == [("datasets/1234", "test-key", (5, 11), None)]
    with pytest.raises(FileExistsError):
        mos_api_client.fetch_dataset(1234, "hospitals", output_dir=tmp_path)


def test_manual_fetch_reads_all_pages(monkeypatch) -> None:
    offsets = []

    def fake_api_get(path, *, api_key, params, timeout, session=None):
        assert params == {"$top": 2, "$skip": len(offsets) * 2}
        offsets.append(params["$skip"])
        start = params["$skip"]
        return [{"global_id": offset} for offset in range(start, min(5, start + 2))]

    monkeypatch.setattr(mos_api_client, "api_get", fake_api_get)
    rows = mos_api_client.get_rows(1234, api_key="test-key", limit=2)
    assert [row["global_id"] for row in rows] == [0, 1, 2, 3, 4]
    assert offsets == [0, 2, 4]
