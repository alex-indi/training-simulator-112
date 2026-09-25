"""Идемпотентный импорт методических demo-шаблонов по ключам источников."""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.modules.identity.models import User
from app.modules.incident_classifier.models import DispatchService, IncidentClassifierRule
from app.modules.object_registry.models import ObjectType
from app.modules.scenario_library.models import ScenarioTemplate
from app.modules.scenario_library.router import (
    TemplateInput,
    as_input,
    detail_options,
    populate,
    readiness_errors,
    validate_references,
)

SEED_PATH = Path(__file__).with_name("demo_scenarios.json")


def load_seed() -> list[dict]:
    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Ожидается непустой список demo-сценариев")
    codes = [row.get("seed_code") for row in rows if isinstance(row, dict)]
    if len(codes) != len(rows) or any(not code for code in codes) or len(set(codes)) != len(codes):
        raise ValueError("Пустой или повторяющийся seed_code сценария")
    return rows


async def import_seed() -> dict[str, int]:
    engine = create_database_engine(get_settings())
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    try:
        factory = create_session_factory(engine)
        async with factory() as db:
            instructor = (
                await db.scalars(
                    select(User).where(User.username == "instructor", User.is_active.is_(True))
                )
            ).one_or_none()
            if instructor is None:
                raise RuntimeError("Нужен demo-пользователь instructor")
            for entry in load_seed():
                rule_id = await db.scalar(
                    select(IncidentClassifierRule.id).where(
                        IncidentClassifierRule.source_reference
                        == entry["classifier_source_reference"]
                    )
                )
                type_id = await db.scalar(
                    select(ObjectType.id).where(ObjectType.code == entry["object_type_code"])
                )
                service_ids = []
                for reference in entry["service_source_references"]:
                    service_ids.append(
                        await db.scalar(
                            select(DispatchService.id).where(
                                DispatchService.source_reference == reference
                            )
                        )
                    )
                if rule_id is None or type_id is None or any(item is None for item in service_ids):
                    raise RuntimeError(f"Не найдены источники для {entry['seed_code']}")
                data = TemplateInput.model_validate(
                    {
                        "name": entry["name"],
                        "description": entry["description"],
                        "difficulty": entry["difficulty"],
                        "classifier_rule_id": rule_id,
                        "object_rule": {
                            "selection_mode": "GENERIC",
                            "object_type_id": type_id,
                            "required_tags": entry["required_tags"],
                        },
                        "initial_title": entry["initial_title"],
                        "initial_description": entry["initial_description"],
                        "initial_caller_text": entry["initial_caller_text"],
                        "events": [
                            {
                                **{key: value for key, value in event.items()
                                   if key != "target_service_source_reference"},
                                "target_service_id": (
                                    service_ids[
                                        entry["service_source_references"].index(
                                            event["target_service_source_reference"]
                                        )
                                    ]
                                    if event.get("target_service_source_reference")
                                    else None
                                ),
                            }
                            for event in entry["events"]
                        ],
                        "services": [
                            {"service_id": item, "source": "CLASSIFIER"} for item in service_ids
                        ],
                        "expected_actions": entry["expected_actions"],
                        "criteria": entry["criteria"],
                    }
                )
                await validate_references(db, data)
                existing = (
                    await db.scalars(
                        select(ScenarioTemplate)
                        .where(ScenarioTemplate.seed_code == entry["seed_code"])
                        .options(*detail_options())
                    )
                ).one_or_none()
                if existing is not None and existing.status == "ARCHIVED":
                    stats["unchanged"] += 1
                    continue
                if (
                    existing is not None
                    and existing.status == "READY"
                    and as_input(existing) == data
                ):
                    stats["unchanged"] += 1
                    continue
                if existing is None:
                    row = ScenarioTemplate(
                        seed_code=entry["seed_code"], created_by_user_id=instructor.id
                    )
                    db.add(row)
                    stats["created"] += 1
                else:
                    row = existing
                    row.object_rule = None
                    row.events = []
                    row.services = []
                    row.expected_actions = []
                    row.criteria = []
                    await db.flush()
                    row.version += 1
                    stats["updated"] += 1
                populate(row, data)
                await db.flush()
                errors = await readiness_errors(db, row)
                if errors:
                    raise RuntimeError(f"Некорректный seed {entry['seed_code']}: {errors}")
                row.status = "READY"
            await db.commit()
    finally:
        await engine.dispose()
    return stats


if __name__ == "__main__":
    print(asyncio.run(import_seed()))
