"""Воспроизводимая библиотека подготовленных карточек для демонстрации."""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.modules.identity.models import User
from app.modules.scenario_library.instance_models import (
    SavedIncidentCard,
    SavedIncidentCardPackage,
)
from app.modules.scenario_library.models import ScenarioTemplate

SEED_ROOT = Path(__file__).resolve().parents[2] / "seed" / "demo"


def load_content(filename: str) -> list[dict]:
    rows = json.loads((SEED_ROOT / filename).read_text(encoding="utf-8"))
    codes = (
        [row.get("seed_code") for row in rows if isinstance(row, dict)]
        if isinstance(rows, list) else []
    )
    if not codes or len(codes) != len(rows) or any(not code for code in codes):
        raise ValueError(f"{filename}: нужны записи с seed_code")
    if len(codes) != len(set(codes)):
        raise ValueError(f"{filename}: повторяется seed_code")
    return rows


async def seed_demo_content() -> dict[str, dict[str, int]]:
    from app.modules.scenario_library.instances import GenerationInput, _build, _matching_objects
    from app.modules.scenario_library.router import get_template

    engine = create_database_engine(get_settings())
    stats = {
        "saved_cards": {"created": 0, "updated": 0, "unchanged": 0},
        "card_packages": {"created": 0, "updated": 0, "unchanged": 0},
    }
    try:
        factory = create_session_factory(engine)
        async with factory() as db:
            instructor = (await db.scalars(select(User).where(User.username == "instructor"))).one()
            templates = {
                row.seed_code: row
                for row in (await db.scalars(select(ScenarioTemplate))).all()
                if row.seed_code
            }
            cards = {
                row.snapshot.get("template_snapshot", {}).get("demo_seed_code"): row
                for row in (await db.scalars(select(SavedIncidentCard))).all()
                if row.snapshot.get("template_snapshot", {}).get("demo_seed_code")
            }
            for entry in load_content("cards.json"):
                template = templates.get(entry["template"])
                if template is None:
                    raise RuntimeError(f"Нет demo-шаблона {entry['template']}")
                template = await get_template(db, template.id)
                objects = await _matching_objects(db, template)
                if len(objects) <= entry["object_index"]:
                    raise RuntimeError(f"Недостаточно объектов для {entry['seed_code']}")
                content = await _build(
                    db,
                    template.id,
                    GenerationInput(
                        object_id=objects[entry["object_index"]].id,
                        seed=entry["seed"],
                    ),
                    instructor,
                )
                snapshot = {
                    key: content[key]
                    for key in (
                        "difficulty", "generation_seed", "classifier_snapshot",
                        "object_snapshot", "service_snapshot", "initial_state_snapshot",
                        "expected_actions_snapshot", "assessment_criteria_snapshot",
                        "template_snapshot", "events",
                    )
                }
                initial = dict(snapshot["initial_state_snapshot"])
                initial["render"] = {
                    "rendered_text": " ".join(
                        part
                        for part in (
                            initial["description"],
                            initial.get("caller_text"),
                            entry["narrative"],
                        )
                        if part
                    )
                }
                snapshot["initial_state_snapshot"] = initial
                snapshot["template_snapshot"] = {
                    **snapshot["template_snapshot"], "demo_seed_code": entry["seed_code"]
                }
                card = cards.get(entry["seed_code"])
                if card is None:
                    card = SavedIncidentCard(
                        created_by_user_id=instructor.id,
                        source_template_id=template.id,
                        name=content["name"],
                        snapshot=snapshot,
                    )
                    db.add(card)
                    cards[entry["seed_code"]] = card
                    stats["saved_cards"]["created"] += 1
                elif (
                    card.name != content["name"]
                    or card.snapshot != snapshot
                    or card.source_template_id != template.id
                    or card.deleted_at is not None
                ):
                    card.name = content["name"]
                    card.snapshot = snapshot
                    card.source_template_id = template.id
                    card.deleted_at = None
                    stats["saved_cards"]["updated"] += 1
                else:
                    stats["saved_cards"]["unchanged"] += 1
            await db.flush()
            packages = {
                row.name: row
                for row in (await db.scalars(select(SavedIncidentCardPackage))).all()
                if row.created_by_user_id == instructor.id
            }
            for entry in load_content("card_packages.json"):
                name = entry["name"]
                ids = [cards[code].id for code in entry["cards"]]
                legacy_names = {
                    "DEMO_PACKAGE_START": "[Демо] Первые решения ДДС",
                    "DEMO_PACKAGE_COMPLEX": "[Демо] Объекты с массовым пребыванием людей",
                }
                package = packages.get(name) or packages.get(legacy_names[entry["seed_code"]])
                if package is None:
                    db.add(SavedIncidentCardPackage(
                        created_by_user_id=instructor.id,
                        name=name,
                        description=entry["description"],
                        card_ids=ids,
                    ))
                    stats["card_packages"]["created"] += 1
                elif (package.name != name or package.description != entry["description"]
                      or package.card_ids != ids
                      or package.deleted_at is not None):
                    package.name = name
                    package.description = entry["description"]
                    package.card_ids = ids
                    package.deleted_at = None
                    stats["card_packages"]["updated"] += 1
                else:
                    stats["card_packages"]["unchanged"] += 1
            await db.commit()
    finally:
        await engine.dispose()
    return stats


if __name__ == "__main__":
    for name, result in asyncio.run(seed_demo_content()).items():
        print(f"{name}: {result}")
