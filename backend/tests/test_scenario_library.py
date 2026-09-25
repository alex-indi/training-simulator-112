"""API contract for the scenario library using the real ORM on a small SQLite fixture."""

import asyncio

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
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
from app.modules.scenario_library.models import (
    ScenarioAssessmentCriterion,
    ScenarioEventTemplate,
    ScenarioExpectedAction,
    ScenarioTemplate,
    ScenarioTemplateObjectRule,
    ScenarioTemplateRequiredObjectTag,
    ScenarioTemplateService,
)
from app.modules.scenario_library.router import router


class AsyncAdapter:
    def __init__(self, session):
        self.session = session

    async def get(self, *args):
        return self.session.get(*args)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def execute(self, statement):
        return self.session.execute(statement)

    async def flush(self):
        self.session.flush()

    async def commit(self):
        self.session.commit()

    def add(self, item):
        self.session.add(item)


def test_library_lifecycle_and_permissions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tables = [
        User,
        IncidentClassifierRule,
        DispatchService,
        IncidentRuleService,
        ObjectType,
        ObjectTagDefinition,
        CityObject,
        ObjectTag,
        ScenarioTemplate,
        ScenarioTemplateObjectRule,
        ScenarioTemplateRequiredObjectTag,
        ScenarioEventTemplate,
        ScenarioTemplateService,
        ScenarioExpectedAction,
        ScenarioAssessmentCriterion,
    ]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    with Session(engine, expire_on_commit=False) as db:
        instructor = User(username="instructor", full_name="Instructor", role=UserRole.INSTRUCTOR)
        admin = User(username="admin", full_name="Administrator", role=UserRole.ADMIN)
        trainee = User(username="trainee", full_name="Trainee", role=UserRole.TRAINEE)
        rule = IncidentClassifierRule(
            incident_group="Пожар", final_incident_type="Пожар", source_reference="SRC:1"
        )
        service = DispatchService(official_name="Пожарная охрана", source_reference="CAT:1")
        other_service = DispatchService(official_name="Скорая помощь", source_reference="CAT:2")
        object_type = ObjectType(code="SCHOOL", name="Школа", source="test")
        empty_type = ObjectType(code="HOSPITAL", name="Больница", source="test")
        db.add_all(
            [
                instructor,
                admin,
                trainee,
                rule,
                service,
                other_service,
                object_type,
                empty_type,
                ObjectTagDefinition(code="children", name="Дети"),
            ]
        )
        db.flush()
        db.add(
            IncidentRuleService(rule_id=rule.id, service_id=service.id, source_reference="SRC:1")
        )
        school = CityObject(
            external_id="1",
            name="Школа №1",
            object_type_id=object_type.id,
            source="test",
            district="Щукино",
            address="улица Пехотная, 1",
        )
        db.add(school)
        db.flush()
        db.add(ObjectTag(object_id=school.id, tag="children"))
        db.commit()
        app = FastAPI()
        app.include_router(router)
        principal = {"user": instructor}

        async def db_override():
            yield AsyncAdapter(db)

        async def user_override():
            return principal["user"]

        app.dependency_overrides[get_database_session] = db_override
        app.dependency_overrides[get_current_user] = user_override

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                catalog = await client.get("/api/scenario-templates/catalog?q=Пехотная")
                assert [item["id"] for item in catalog.json()["objects"]] == [school.id]
                created = await client.post(
                    "/api/scenario-templates", json={"name": "Пожар в школе"}
                )
                assert created.status_code == 201, created.text
                scenario_id = created.json()["id"]
                assert (
                    await client.post(f"/api/scenario-templates/{scenario_id}/ready")
                ).status_code == 422
                payload = {
                    "name": "Пожар в школе",
                    "difficulty": 4,
                    "classifier_rule_id": rule.id,
                    "object_rule": {
                        "selection_mode": "GENERIC",
                        "object_type_id": object_type.id,
                        "required_tags": ["children"],
                    },
                    "initial_title": "Дым",
                    "initial_description": "Из школы идёт дым",
                    "events": [
                        {"offset_seconds": 0, "event_type": "INITIAL_REPORT", "title": "Заявитель"}
                    ],
                    "services": [{"service_id": service.id, "source": "CLASSIFIER"}],
                    "criteria": [{"name": "Реакция"}],
                }
                bad = await client.patch(
                    f"/api/scenario-templates/{scenario_id}",
                    json={**payload, "services": [{"service_id": 999}]},
                )
                assert bad.status_code == 422
                bad_type = await client.patch(
                    f"/api/scenario-templates/{scenario_id}",
                    json={
                        **payload,
                        "object_rule": {**payload["object_rule"], "object_type_id": 999},
                    },
                )
                assert bad_type.status_code == 422
                missing_object = await client.patch(
                    f"/api/scenario-templates/{scenario_id}",
                    json={**payload, "object_rule": {
                        **payload["object_rule"],
                        "selection_mode": "OBJECT_BOUND",
                        "specific_object_id": 999,
                    }},
                )
                assert missing_object.status_code == 422
                saved = await client.patch(f"/api/scenario-templates/{scenario_id}", json=payload)
                assert saved.status_code == 200, saved.text
                no_match = await client.patch(
                    f"/api/scenario-templates/{scenario_id}",
                    json={**payload, "object_rule": {
                        **payload["object_rule"],
                        "object_type_id": empty_type.id,
                        "required_tags": [],
                    }},
                )
                assert no_match.status_code == 200
                assert (await client.get(f"/api/scenario-templates/{scenario_id}/validate")).json()[
                    "matching_object_count"
                ] == 0
                assert (
                    await client.post(f"/api/scenario-templates/{scenario_id}/ready")
                ).status_code == 422
                no_initial = await client.patch(
                    f"/api/scenario-templates/{scenario_id}", json={**payload, "events": []}
                )
                assert no_initial.status_code == 200
                assert (
                    await client.post(f"/api/scenario-templates/{scenario_id}/ready")
                ).status_code == 422
                revised = await client.patch(
                    f"/api/scenario-templates/{scenario_id}",
                    json={**payload, "initial_description": "Уточнённый дым"},
                )
                assert revised.status_code == 200, revised.text
                assert revised.json()["version"] == 5
                check = await client.get(f"/api/scenario-templates/{scenario_id}/validate")
                assert check.json() == {"errors": [], "matching_object_count": 1}
                ready = await client.post(f"/api/scenario-templates/{scenario_id}/ready")
                assert ready.status_code == 200, ready.text
                assert ready.json()["incident_type"] == "Пожар"
                assert (await client.get("/api/scenario-templates?district=Щукино")).json()[
                    "total"
                ] == 0
                assert (await client.get("/api/scenario-templates")).json()["total"] == 1
                filtered = await client.get(f"/api/scenario-templates?service_id={service.id}")
                assert filtered.json()["total"] == 1
                assert (await client.get("/api/scenario-templates?difficulty=1")).json()[
                    "total"
                ] == 0
                copy = await client.post(f"/api/scenario-templates/{scenario_id}/duplicate")
                assert copy.status_code == 201, copy.text
                assert copy.json()["status"] == "DRAFT"
                assert copy.json()["events"][0]["title"] == "Заявитель"
                copy_id = copy.json()["id"]
                message_events = [
                    *payload["events"],
                    {
                        "offset_seconds": 60,
                        "event_type": "RESPONSE_MESSAGE",
                        "title": "Доклад группы",
                    },
                ]
                missing_target = await client.patch(
                    f"/api/scenario-templates/{copy_id}",
                    json={**payload, "events": message_events},
                )
                assert missing_target.status_code == 200
                assert "Выберите службу для сообщения группы" in (
                    await client.get(f"/api/scenario-templates/{copy_id}/validate")
                ).json()["errors"]
                assert (
                    await client.post(f"/api/scenario-templates/{copy_id}/ready")
                ).status_code == 422
                outside_target = await client.patch(
                    f"/api/scenario-templates/{copy_id}",
                    json={**payload, "events": [
                        *payload["events"],
                        {**message_events[1], "target_service_id": other_service.id},
                    ]},
                )
                assert outside_target.status_code == 422
                addressed = await client.patch(
                    f"/api/scenario-templates/{copy_id}",
                    json={**payload, "events": [
                        *payload["events"],
                        {**message_events[1], "target_service_id": service.id},
                    ]},
                )
                assert addressed.status_code == 200
                assert addressed.json()["events"][1]["target_service_id"] == service.id
                assert (
                    await client.get(f"/api/scenario-templates/{copy_id}/validate")
                ).json()["errors"] == []
                denied_author = await client.patch(
                    f"/api/scenario-templates/{copy_id}",
                    json={**payload, "created_by_user_id": admin.id},
                )
                assert denied_author.status_code == 403
                principal["user"] = admin
                admin_created = await client.post(
                    "/api/scenario-templates",
                    json={"name": "Сценарий преподавателя", "created_by_user_id": instructor.id},
                )
                assert admin_created.status_code == 201, admin_created.text
                assert admin_created.json()["created_by_user_id"] == instructor.id
                principal["user"] = trainee
                assert (
                    await client.get(f"/api/scenario-templates/{scenario_id}")
                ).status_code == 403
                principal["user"] = instructor
                assert (
                    await client.post(f"/api/scenario-templates/{scenario_id}/archive")
                ).status_code == 200
                assert (await client.get("/api/scenario-templates")).json()["total"] == 0

        asyncio.run(run())
    engine.dispose()
