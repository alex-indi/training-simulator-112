"""Round-trip checks for administrator JSON data exchange."""

import asyncio
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.admin.data_exchange import export_dataset, import_dataset
from app.modules.incident_classifier.models import DispatchService
from app.modules.object_registry.models import (
    CityObject,
    ObjectAttribute,
    ObjectTag,
    ObjectTagDefinition,
    ObjectType,
)


class AsyncAdapter:
    def __init__(self, session: Session):
        self.session = session

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def flush(self):
        self.session.flush()

    def add(self, item):
        self.session.add(item)


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tables = [
        DispatchService,
        ObjectType,
        ObjectTagDefinition,
        CityObject,
        ObjectAttribute,
        ObjectTag,
    ]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    return Session(engine, expire_on_commit=False)


def test_service_export_is_directly_importable_and_idempotent() -> None:
    with _session() as db:
        db.add(
            DispatchService(
                source_reference="SERVICE:101",
                official_name="Служба 101",
                organization="МЧС",
                service_level="ГОРОД",
            )
        )
        db.flush()
        session = AsyncAdapter(db)

        envelope = asyncio.run(export_dataset(session, "services"))
        envelope["records"][0]["official_name"] = "Пожарно-спасательная служба"
        first = asyncio.run(import_dataset(session, "services", envelope["records"]))
        second = asyncio.run(import_dataset(session, "services", envelope["records"]))

        service = db.scalar(select(DispatchService))
        assert envelope["format"] == "ut112-admin-data"
        assert first == {"received": 1, "created": 0, "updated": 1, "skipped": 0}
        assert second == {"received": 1, "created": 0, "updated": 0, "skipped": 1}
        assert service.official_name == "Пожарно-спасательная служба"


def test_object_round_trip_preserves_hierarchy_attributes_and_tags() -> None:
    with _session() as db:
        parent = ObjectType(code="EDUCATION", name="Образование", source="CORE")
        child = ObjectType(code="SCHOOL", name="Школа", source="CORE", parent=parent)
        db.add_all(
            [
                parent,
                child,
                ObjectTagDefinition(code="children", name="Дети"),
            ]
        )
        db.flush()
        city_object = CityObject(
            source="DEMO",
            external_id="school-1",
            name="Школа № 1",
            object_type_id=child.id,
            latitude=Decimal("55.751244"),
            longitude=Decimal("37.618423"),
        )
        db.add(city_object)
        db.flush()
        db.add_all(
            [
                ObjectAttribute(
                    object_id=city_object.id,
                    attribute_code="working_hours",
                    value='{"monday": "08:00–20:00"}',
                    value_type="json",
                ),
                ObjectTag(object_id=city_object.id, tag="children"),
            ]
        )
        db.flush()
        session = AsyncAdapter(db)

        envelope = asyncio.run(export_dataset(session, "objects"))
        record = envelope["records"]["objects"][0]
        record["name"] = "Школа № 1 (обновлено)"
        result = asyncio.run(import_dataset(session, "objects", envelope["records"]))

        assert envelope["records"]["object_types"][1]["parent_code"] == "EDUCATION"
        assert record["attributes"] == {"working_hours": {"monday": "08:00–20:00"}}
        assert record["tags"] == ["children"]
        assert result["updated"] == 1
        assert city_object.name == "Школа № 1 (обновлено)"
