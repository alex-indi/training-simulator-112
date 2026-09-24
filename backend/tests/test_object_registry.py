"""Реестр остаётся расширяемым без изменений схемы или ветвления по типам."""

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.incident_classifier.models import IncidentFeature
from app.modules.object_registry.models import (
    CityObject,
    ObjectAttribute,
    ObjectTag,
    ObjectTagClassifierFeature,
    ObjectTagDefinition,
    ObjectType,
)
from app.modules.object_registry.queries import (
    descendant_type_ids,
    select_city_objects,
    select_city_objects_for_classifier_features,
)
from seed.import_object_tag_classifier_features import load_links, upsert_links
from seed.import_object_tags import load_object_tags, upsert_object_tags
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
            IncidentFeature.__table__,
            ObjectTagDefinition.__table__,
            ObjectTag.__table__,
            ObjectTagClassifierFeature.__table__,
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
    upsert_object_tags(session, load_object_tags())
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
    assert "METRO_STATION" in building_codes
    healthcare_codes = set(
        session.scalars(
            select(ObjectType.code).where(ObjectType.id.in_(descendant_type_ids("HEALTHCARE")))
        )
    )
    assert healthcare_codes == {"HEALTHCARE", "HOSPITAL", "POLYCLINIC", "EMERGENCY_STATION"}
    assert shopping.id is not None


def test_tag_query_finds_objects_across_types(session: Session) -> None:
    types = seed_types(session)
    upsert_object_tags(session, load_object_tags())
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
        tags=[ObjectTag(tag="medical"), ObjectTag(tag="mass_people")],
    )
    session.add_all([school, metro, hospital])
    session.flush()

    assert {obj.name for obj in session.scalars(select_city_objects(tags=["mass_people"]))} == {
        "Школа",
        "Метро",
        "Больница",
    }
    assert {
        obj.name
        for obj in session.scalars(select_city_objects(type_code="BUILDING", tags=["mass_people"]))
    } == {"Школа", "Метро", "Больница"}
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


def test_classifier_feature_links_select_only_matching_objects(session: Session) -> None:
    types = seed_types(session)
    upsert_object_tags(session, load_object_tags())
    feature = IncidentFeature(
        name="Учебное заведение",
        level="2",
        source_column="112-Признак.2",
        source_value="Учебное заведение",
    )
    session.add(feature)
    session.add_all(
        [
            CityObject(
                source="test",
                external_id="school",
                name="Школа",
                object_type=types["SCHOOL"],
                tags=[ObjectTag(tag="education")],
            ),
            CityObject(
                source="test",
                external_id="hospital",
                name="Больница",
                object_type=types["HOSPITAL"],
                tags=[ObjectTag(tag="medical")],
            ),
        ]
    )
    session.flush()
    with pytest.raises(ValueError, match="Неизвестная связь"):
        upsert_links(session, [{"tag_code": "education", "feature_key": ["2", "x", "x"]}])
    transport_feature = IncidentFeature(
        name="транспорт",
        level="1",
        source_column="112 - Признак.1 (тип происшествия)",
        source_value="транспорт",
    )
    education_feature = IncidentFeature(
        name="Учебное заведение",
        level="1",
        source_column="112 - Признак.1 (тип происшествия)",
        source_value="Учебное заведение",
    )
    session.add_all([transport_feature, education_feature])
    session.flush()
    upsert_links(session, load_links())
    upsert_links(session, load_links())
    assert [
        obj.name
        for obj in session.scalars(
            select_city_objects_for_classifier_features([feature.id], type_code="BUILDING")
        )
    ] == ["Школа"]
