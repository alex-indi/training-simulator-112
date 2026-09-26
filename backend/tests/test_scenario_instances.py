"""Generation keeps a fixed, instructor-only snapshot of verified source data."""

import asyncio

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_scenario_library import AsyncAdapter

from app.db.base import Base
from app.db.dependencies import get_database_session
from app.modules.admin.models import AdminAudit, AIProviderConfig, AIUsageDaily, UserGroup
from app.modules.admin.router import router as admin_router
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.incident_classifier.models import (
    DispatchService,
    IncidentClassifierRule,
    IncidentFeature,
    IncidentRuleFeature,
    IncidentRuleService,
)
from app.modules.incidents import models as incident_models  # noqa: F401
from app.modules.object_registry.models import (
    CityObject,
    ObjectAttribute,
    ObjectTag,
    ObjectTagDefinition,
    ObjectType,
)
from app.modules.response import models as response_models  # noqa: F401
from app.modules.scenario_library.instance_models import (
    SavedIncidentCard,
    ScenarioInstance,
    ScenarioInstanceEvent,
)
from app.modules.scenario_library.instances import instance_router, session_router, template_router
from app.modules.scenario_library.models import (
    ScenarioAssessmentCriterion,
    ScenarioEventTemplate,
    ScenarioExpectedAction,
    ScenarioTemplate,
    ScenarioTemplateObjectRule,
    ScenarioTemplateRequiredObjectTag,
    ScenarioTemplateService,
)
from app.modules.scenario_library.router import router as library_router
from app.modules.scenario_library.saved_cards import router as saved_cards_router
from app.modules.training.models import TrainingGroup, TrainingSession
from app.services.text_generation.providers import OpenAICompatibleProvider
from app.services.text_generation.renderer import (
    ProviderHealth,
    TextGenerationResult,
)


def test_generation_snapshot_permissions_and_session_attachment(monkeypatch):
    async def fake_generate(self, request, prompt):
        if request.context and request.context.get("previous_text"):
            assert "Сформулируй новую запись заметно иначе" in prompt
            assert "Используй только факты из facts" in prompt
        return TextGenerationResult(
            text=(
                "Новая оперативная формулировка"
                if request.context and request.context.get("previous_text")
                else "Подготовленный локальный текст"
            ),
            provider=self.name,
            model=self.model,
            input_tokens=7,
            output_tokens=3,
        )

    async def fake_healthcheck(self):
        return ProviderHealth("AVAILABLE", self.name, self.model)

    monkeypatch.setattr(OpenAICompatibleProvider, "generate", fake_generate)
    monkeypatch.setattr(OpenAICompatibleProvider, "healthcheck", fake_healthcheck)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tables = [
        User,
        UserGroup,
        AIProviderConfig,
        AIUsageDaily,
        AdminAudit,
        IncidentClassifierRule,
        IncidentFeature,
        IncidentRuleFeature,
        DispatchService,
        IncidentRuleService,
        ObjectType,
        ObjectTagDefinition,
        CityObject,
        ObjectAttribute,
        ObjectTag,
        TrainingSession,
        TrainingGroup,
        ScenarioTemplate,
        ScenarioTemplateObjectRule,
        ScenarioTemplateRequiredObjectTag,
        ScenarioEventTemplate,
        ScenarioTemplateService,
        ScenarioExpectedAction,
        ScenarioAssessmentCriterion,
        ScenarioInstance,
        ScenarioInstanceEvent,
        SavedIncidentCard,
    ]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    with Session(engine, expire_on_commit=False) as db:
        instructor = User(username="instructor", full_name="Instructor", role=UserRole.INSTRUCTOR)
        trainee = User(username="trainee", full_name="Trainee", role=UserRole.TRAINEE)
        admin = User(username="admin", full_name="Admin", role=UserRole.ADMIN)
        rule = IncidentClassifierRule(
            incident_group="Пожар", final_incident_type="Пожар в школе", source_reference="SRC:1"
        )
        feature = IncidentFeature(
            name="Дым", level="MAIN", source_column="ПРИЗНАК", source_value="Дым"
        )
        service = DispatchService(official_name="Пожарная охрана", source_reference="CAT:1")
        school_type = ObjectType(code="SCHOOL", name="Школа", source="test")
        db.add_all(
            [
                instructor,
                trainee,
                admin,
                rule,
                feature,
                service,
                school_type,
                ObjectTagDefinition(code="children", name="Дети"),
            ]
        )
        db.flush()
        db.add_all(
            [
                IncidentRuleFeature(rule_id=rule.id, feature_id=feature.id),
                IncidentRuleService(
                    rule_id=rule.id, service_id=service.id, source_reference="SRC:1"
                ),
            ]
        )
        school = CityObject(
            external_id="1",
            name="Школа №1",
            object_type_id=school_type.id,
            source="test",
            address="Пехотная, 1",
            district="Щукино",
        )
        db.add(school)
        db.flush()
        db.add_all(
            [
                ObjectTag(object_id=school.id, tag="children"),
                ObjectAttribute(
                    object_id=school.id,
                    attribute_code="capacity",
                    value="100",
                    value_type="integer",
                ),
            ]
        )
        other_school = CityObject(
            external_id="2",
            name="Школа №2",
            object_type_id=school_type.id,
            source="test",
            address="Пехотная, 2",
            district="Щукино",
        )
        db.add(other_school)
        db.flush()
        db.add(ObjectTag(object_id=other_school.id, tag="children"))
        extra_schools = [
            CityObject(
                external_id=str(index),
                name=f"Школа №{index}",
                object_type_id=school_type.id,
                source="test",
                address=f"Пехотная, {index}",
                district="Щукино",
            )
            for index in range(3, 6)
        ]
        db.add_all(extra_schools)
        db.flush()
        db.add_all(ObjectTag(object_id=item.id, tag="children") for item in extra_schools)
        template = ScenarioTemplate(
            name="Пожар в школе",
            status="READY",
            difficulty=4,
            classifier_rule_id=rule.id,
            created_by_user_id=instructor.id,
            initial_title="Дым",
            initial_description="Из здания идёт дым",
            object_rule=ScenarioTemplateObjectRule(
                selection_mode="GENERIC",
                object_type_id=school_type.id,
                required_tags=[ScenarioTemplateRequiredObjectTag(tag="children")],
            ),
            events=[
                ScenarioEventTemplate(
                    sequence_number=0,
                    offset_seconds=0,
                    event_type="INITIAL_REPORT",
                    title="Заявитель",
                    description="Сообщил о дыме",
                    source_type="CALLER",
                ),
                ScenarioEventTemplate(
                    sequence_number=1,
                    offset_seconds=60,
                    event_type="RESPONSE_MESSAGE",
                    title="Прибытие",
                    description="Бригада прибыла",
                    source_type="RESPONSE_UNIT",
                    target_service_id=service.id,
                ),
            ],
            services=[ScenarioTemplateService(service_id=service.id, source="CLASSIFIER")],
            expected_actions=[
                ScenarioExpectedAction(
                    expected_action_type="NOTIFY", expected_service_id=service.id
                )
            ],
            criteria=[ScenarioAssessmentCriterion(name="Время реакции", weight=3)],
        )
        session = TrainingSession(title="Занятие", instructor_id=instructor.id)
        group = TrainingGroup(name="Группа без АРМ", difficulty="Начальная")
        session.groups.append(group)
        db.add_all([template, session])
        db.commit()
        app = FastAPI()
        app.include_router(library_router)
        app.include_router(template_router)
        app.include_router(instance_router)
        app.include_router(session_router)
        app.include_router(saved_cards_router)
        app.include_router(admin_router)
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
                path = f"/api/scenario-templates/{template.id}"
                preview = await client.post(f"{path}/generate-preview", json={"seed": 12})
                assert preview.status_code == 200, preview.text
                assert preview.json()["matching_objects"][0]["id"] == school.id
                assert preview.json()["object_snapshot"] is None
                searched = await client.post(
                    f"{path}/generate-preview", json={"object_query": "№2"}
                )
                assert [item["id"] for item in searched.json()["matching_objects"]] == [
                    other_school.id
                ]
                random_input = {"seed": 12, "variant_mode": "RANDOM"}
                first_random = (
                    await client.post(f"{path}/generate-preview", json=random_input)
                ).json()
                second_random = (
                    await client.post(f"{path}/generate-preview", json=random_input)
                ).json()
                assert first_random["object_snapshot"] == second_random["object_snapshot"]
                template.status = "DRAFT"
                db.commit()
                assert (
                    await client.post(f"{path}/generate-preview", json=random_input)
                ).status_code == 200
                template.status = "READY"
                db.commit()
                payload = {"object_id": school.id, "seed": 12, "difficulty": 5}
                generated = await client.post(f"{path}/instances", json=payload)
                assert generated.status_code == 201, generated.text
                instance = generated.json()
                assert [
                    item["id"] for item in (await client.get("/api/scenario-instances")).json()
                ] == [instance["id"]]
                assert instance["object_snapshot"]["address"] == "Пехотная, 1"
                assert instance["classifier_snapshot"]["features"][0]["name"] == "Дым"
                assert instance["service_snapshot"][0]["official_name"] == "Пожарная охрана"
                assert instance["assessment_criteria_snapshot"][0]["weight"] == 3
                assert instance["events"][0]["description"] == "Сообщил о дыме"
                assert instance["events"][1]["payload_snapshot"]["target_service_id"] == service.id
                assert (
                    instance["events"][1]["payload_snapshot"]["target_service_name"]
                    == "Пожарная охрана"
                )
                assert instance["status"] == "DRAFT"
                assert instance["initial_state_snapshot"]["render"]["fallback_used"]
                assert instance["events"][1]["render"]["rendered_text"] == "Бригада прибыла"
                usage = db.scalar(select(AIUsageDaily))
                assert usage.requests == 2 and usage.fallbacks == 2
                base = f"/api/scenario-instances/{instance['id']}"
                edited = await client.patch(
                    f"{base}/initial-message", json={"text": "Сообщение преподавателя"}
                )
                assert edited.status_code == 200, edited.text
                assert (
                    edited.json()["initial_state_snapshot"]["render"]["render_origin"] == "MANUAL"
                )
                assert (
                    edited.json()["initial_state_snapshot"]["description"] == "Из здания идёт дым"
                )
                event_id = instance["events"][1]["id"]
                changed = await client.patch(
                    f"{base}/events/{event_id}/message", json={"text": "Прибыли к месту"}
                )
                assert changed.status_code == 200, changed.text
                assert changed.json()["events"][1]["render"]["render_origin"] == "MANUAL"
                assert (await client.get(base)).json()["events"][1]["render"][
                    "rendered_text"
                ] == "Прибыли к месту"
                confirmed = await client.post(f"{base}/confirm")
                assert confirmed.status_code == 200, confirmed.text
                assert confirmed.json()["status"] == "CONFIRMED"
                assert (
                    await client.patch(f"{base}/initial-message", json={"text": "Поздно"})
                ).status_code == 409
                assert (await client.post(f"{base}/events/{event_id}/rerender")).status_code == 409
                repeated = await client.post(f"{path}/instances", json=payload)
                assert repeated.json()["object_snapshot"] == instance["object_snapshot"]
                assert (
                    repeated.json()["events"][0]["payload_snapshot"]
                    == instance["events"][0]["payload_snapshot"]
                )
                principal["user"] = admin
                configuration = await client.put(
                    "/api/admin/ai",
                    json={
                        "provider": "OPENAI_COMPATIBLE",
                        "model": "local-test",
                        "base_url": "http://local.test/v1",
                        "enabled": True,
                        "timeout_seconds": 7,
                    },
                )
                assert configuration.status_code == 200, configuration.text
                assert "api_key" not in configuration.json()
                wrong_endpoint = await client.put(
                    "/api/admin/ai",
                    json={
                        "provider": "OPENAI",
                        "model": "test-model",
                        "base_url": "http://local.test/v1",
                        "enabled": True,
                        "timeout_seconds": 7,
                    },
                )
                assert wrong_endpoint.status_code == 422
                assert (await client.post("/api/admin/ai/health")).json()["status"] == "AVAILABLE"
                principal["user"] = instructor
                configured = await client.post(f"{path}/instances", json=payload)
                assert configured.status_code == 201, configured.text
                assert (
                    configured.json()["initial_state_snapshot"]["render"]["model"] == "local-test"
                )
                assert configured.json()["events"][1]["render"]["provider"] == "openai_compatible"
                db.expire_all()
                principal["user"] = admin
                daily = (await client.get("/api/admin/ai/usage")).json()[0]
                assert daily["requests"] == 6
                assert daily["input_tokens"] == 14 and daily["output_tokens"] == 6
                principal["user"] = instructor
                assert (
                    await client.post(f"{path}/instances", json={"object_id": 999})
                ).status_code == 422
                attached = await client.post(
                    f"/api/scenario-instances/{instance['id']}/attach",
                    json={"training_session_id": session.id},
                )
                assert attached.status_code == 200, attached.text
                assert (
                    len(
                        (
                            await client.get(
                                f"/api/training/sessions/{session.id}/scenario-instances"
                            )
                        ).json()
                    )
                    == 1
                )
                template.seed_code = "DEMO_EDUCATION_FIRE_001"
                db.commit()
                batch_input = {
                    "count": 5,
                    "seed": 43,
                    "training_session_id": session.id,
                    "training_group_id": group.id,
                }
                insufficient = await client.post(f"{path}/batch", json={**batch_input, "count": 6})
                assert insufficient.status_code == 422
                assert "разных подходящих объектов" in insufficient.json()["detail"]
                repeated_objects = await client.post(
                    f"{path}/batch",
                    json={**batch_input, "count": 6, "distinct_objects": False},
                )
                assert repeated_objects.status_code == 201, repeated_objects.text
                assert len(repeated_objects.json()) == 6
                for card in repeated_objects.json():
                    assert (
                        await client.delete(f"/api/scenario-instances/{card['id']}")
                    ).status_code == 204
                batch = await client.post(f"{path}/batch", json=batch_input)
                assert batch.status_code == 201, batch.text
                cards = batch.json()
                assert len(cards) == 5
                assert len({card["object_snapshot"]["id"] for card in cards}) == 5
                assert all(card["difficulty"] == 1 for card in cards)
                assert (
                    len(
                        {
                            (
                                card["object_snapshot"]["id"],
                                tuple(
                                    sorted(card["initial_state_snapshot"]["variant_facts"].items())
                                ),
                            )
                            for card in cards
                        }
                    )
                    == 5
                )
                assert cards[0]["object_snapshot"]["id"] != cards[1]["object_snapshot"]["id"]
                assert all(card["training_session_id"] == session.id for card in cards)
                assert all(card["training_group_id"] == group.id for card in cards)
                assert [card["template_snapshot"]["batch_position"] for card in cards] == [
                    1,
                    2,
                    3,
                    4,
                    5,
                ]
                assert all(card["template_snapshot"]["batch_seed"] == 43 for card in cards)
                first_card = f"/api/scenario-instances/{cards[0]['id']}"
                rerendered = await client.post(f"{first_card}/rerender-initial-message")
                assert rerendered.status_code == 200, rerendered.text
                old_text = cards[0]["initial_state_snapshot"]["render"]["rendered_text"]
                new_text = rerendered.json()["initial_state_snapshot"]["render"]["rendered_text"]
                assert new_text != old_text
                unchanged = await client.post(f"{first_card}/rerender-initial-message")
                assert unchanged.status_code == 409
                assert "Текст карточки не изменился" in unchanged.json()["detail"]
                assert (
                    rerendered.json()["initial_state_snapshot"]["variant_facts"]
                    == cards[0]["initial_state_snapshot"]["variant_facts"]
                )
                new_facts = dict(cards[0]["initial_state_snapshot"]["variant_facts"])
                new_facts["floor"] = 1 if new_facts["floor"] != 1 else 2
                edited = await client.patch(f"{first_card}/variant-facts", json=new_facts)
                assert edited.status_code == 200, edited.text
                assert edited.json()["initial_state_snapshot"]["variant_facts"] == new_facts
                assert edited.json()["object_snapshot"]["id"] == cards[0]["object_snapshot"]["id"]
                assert edited.json()["template_snapshot"]["variant_facts_edited"] is True
                assert (
                    await client.patch(
                        f"{first_card}/variant-facts", json={**new_facts, "floor": 99}
                    )
                ).status_code == 422
                regenerated = await client.post(f"{first_card}/regenerate-card")
                assert regenerated.status_code == 200, regenerated.text
                assert (
                    regenerated.json()["object_snapshot"]["id"],
                    regenerated.json()["initial_state_snapshot"]["variant_facts"],
                ) != (
                    cards[0]["object_snapshot"]["id"],
                    cards[0]["initial_state_snapshot"]["variant_facts"],
                )
                assert regenerated.json()["template_snapshot"]["batch_seed"] == 43
                second_card = f"/api/scenario-instances/{cards[1]['id']}"
                assert (await client.delete(second_card)).status_code == 204
                assert (await client.get(second_card)).status_code == 404
                repeated_batch = await client.post(f"{path}/batch", json=batch_input)
                assert repeated_batch.status_code == 201, repeated_batch.text
                assert [
                    (
                        card["generation_seed"],
                        card["object_snapshot"]["id"],
                        card["initial_state_snapshot"]["variant_facts"],
                    )
                    for card in repeated_batch.json()
                ] == [
                    (
                        card["generation_seed"],
                        card["object_snapshot"]["id"],
                        card["initial_state_snapshot"]["variant_facts"],
                    )
                    for card in cards
                ]
                library_saved = await client.post(
                    f"/api/incident-cards/from-instance/{instance['id']}"
                )
                assert library_saved.status_code == 201, library_saved.text
                card_id = library_saved.json()["id"]
                assert (
                    library_saved.json()["service_snapshot"][0]["official_name"]
                    == "Пожарная охрана"
                )
                school.address = "Изменённый адрес"
                rule.final_incident_type = "Изменённый тип"
                template.initial_title = "Изменённая карточка"
                db.commit()
                saved = (await client.get(f"/api/scenario-instances/{instance['id']}")).json()
                assert saved["object_snapshot"]["address"] == "Пехотная, 1"
                assert saved["classifier_snapshot"]["final_incident_type"] == "Пожар в школе"
                assert saved["initial_state_snapshot"]["title"] == "Дым"
                assert (await client.get(f"/api/incident-cards/{card_id}")).json()[
                    "object_snapshot"
                ]["address"] == "Пехотная, 1"
                copied = await client.post(
                    f"/api/incident-cards/{card_id}/add-to-group",
                    json={"session_id": session.id, "group_id": group.id},
                )
                assert copied.status_code == 201, copied.text
                clone = (await client.get(f"/api/scenario-instances/{copied.json()['id']}")).json()
                assert clone["status"] == "CONFIRMED"
                assert clone["object_snapshot"]["address"] == "Пехотная, 1"
                edited_card = await client.patch(
                    f"/api/incident-cards/{card_id}/text", json={"text": "Проверенный текст"}
                )
                assert edited_card.status_code == 200, edited_card.text
                assert (
                    clone["initial_state_snapshot"]["render"]["rendered_text"]
                    != "Проверенный текст"
                )
                assert (await client.delete(f"/api/incident-cards/{card_id}")).status_code == 204
                assert (await client.get(f"/api/incident-cards/{card_id}")).status_code == 404
                simple = await client.post(
                    "/api/scenario-templates/simple",
                    json={
                        "name": "Пожар в школе",
                        "classifier_rule_id": rule.id,
                        "object_type_id": school_type.id,
                        "variant_options": {"floor": [1, 2]},
                    },
                )
                assert simple.status_code == 201, simple.text
                simple_instance = await client.post(
                    f"/api/scenario-templates/{simple.json()['id']}/instances",
                    json={"object_id": school.id, "seed": 10},
                )
                assert simple_instance.status_code == 201, simple_instance.text
                simple_card = await client.post(
                    f"/api/incident-cards/from-instance/{simple_instance.json()['id']}"
                )
                assert simple_card.status_code == 201, simple_card.text
                simple_card_id = simple_card.json()["id"]
                changed_facts = await client.patch(
                    f"/api/incident-cards/{simple_card_id}/facts",
                    json={"facts": {"floor": 2}},
                )
                assert changed_facts.status_code == 200, changed_facts.text
                assert changed_facts.json()["initial_state_snapshot"]["variant_facts"] == {
                    "floor": 2
                }
                assert (
                    await client.patch(
                        f"/api/incident-cards/{simple_card_id}/facts",
                        json={"facts": {"floor": 99}},
                    )
                ).status_code == 422
                principal["user"] = trainee
                assert (await client.get("/api/incident-cards")).status_code == 403
                assert (
                    await client.get(f"/api/scenario-instances/{instance['id']}")
                ).status_code == 403
                assert (
                    await client.get(f"/api/training/sessions/{session.id}/scenario-instances")
                ).status_code == 403
                assert (await client.get("/api/scenario-instances")).status_code == 403

        asyncio.run(run())
    engine.dispose()
