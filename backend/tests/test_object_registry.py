"""Реестр остаётся расширяемым без изменений схемы или ветвления по типам."""

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.object_registry.models import CityObject, ObjectAttribute, ObjectTag, ObjectType
from app.modules.object_registry.queries import descendant_type_ids, select_city_objects
from seed.import_object_types import load_object_types


@pytest.fixture
def session():
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
    with Session(engine) as db:
        yield db
    engine.dispose()


def seed_types(session: Session) -> dict[str, ObjectType]:
    types: dict[str, ObjectType] = {}
    for row in load_object_types():
        parent = types.get(row["parent_code"])
        item = ObjectType(
            code=row["code"],
            name=row["name"],
            parent=parent,
            description=row["description"],
            source=row["source"],
        )
        session.add(item)
        session.flush()
        types[item.code] = item
    return types


def test_new_type_uses_existing_schema_and_hierarchy(session: Session) -> None:
    types = seed_types(session)
    shopping = ObjectType(
        code="SHOPPING_CENTER", name="Торговый центр", parent=types["BUILDING"], source="test"
    )
    session.add(shopping)
    session.flush()

    building_codes = set(
        session.scalars(
            select(ObjectType.code).where(ObjectType.id.in_(descendant_type_ids("BUILDING")))
        )
    )
    education_codes = set(
        session.scalars(
            select(ObjectType.code).where(ObjectType.id.in_(descendant_type_ids("EDUCATION")))
        )
    )
    assert {"BUILDING", "EDUCATION", "SCHOOL", "SHOPPING_CENTER"} <= building_codes
    assert "SCHOOL" in education_codes
    assert "METRO_STATION" not in building_codes
    assert shopping.id is not None


def test_tag_query_finds_objects_across_types(session: Session) -> None:
    types = seed_types(session)
    school = CityObject(
        external_id="school-1",
        name="Школа",
        object_type=types["SCHOOL"],
        source="test",
        tags=[ObjectTag(tag="mass_people"), ObjectTag(tag="children")],
        attributes=[ObjectAttribute(attribute_code="CAPACITY", value="800", value_type="integer")],
    )
    metro = CityObject(
        external_id="metro-1",
        name="Метро",
        object_type=types["METRO_STATION"],
        source="test",
        tags=[ObjectTag(tag="mass_people")],
    )
    hospital = CityObject(
        external_id="hospital-1",
        name="Больница",
        object_type=types["HOSPITAL"],
        source="test",
        tags=[ObjectTag(tag="medical")],
    )
    session.add_all([school, metro, hospital])
    session.flush()

    assert {obj.name for obj in session.scalars(select_city_objects(tags=["mass_people"]))} == {
        "Школа",
        "Метро",
    }
    assert {
        obj.name
        for obj in session.scalars(select_city_objects(type_code="BUILDING", tags=["mass_people"]))
    } == {"Школа"}
    assert school.attributes[0].value == "800"


def test_seed_rejects_unknown_parent(tmp_path) -> None:
    path = tmp_path / "types.json"
    path.write_text(
        json.dumps(
            [{"code": "SHOPPING_CENTER", "name": "ТЦ", "source": "test", "parent_code": "BUILDING"}]
        )
    )
    with pytest.raises(ValueError, match="Родитель должен предшествовать"):
        load_object_types(path)
