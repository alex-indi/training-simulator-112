"""Load semantic object tag definitions without overwriting local edits."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.object_registry.models import ObjectTagDefinition

SEED_PATH = Path(__file__).with_name("object_tags_dictionary.json")


def load_object_tags(path: Path = SEED_PATH) -> list[dict[str, str]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    codes = [row["code"] for row in rows]
    if len(codes) != len(set(codes)) or any(not row["name"] for row in rows):
        raise ValueError("Некорректный справочник тегов")
    return rows


def upsert_object_tags(session: Session, rows: list[dict[str, str]]) -> None:
    """Add missing definitions and replace migration placeholders with curated metadata."""
    existing = {row.code: row for row in session.scalars(select(ObjectTagDefinition))}
    for row in rows:
        item = existing.get(row["code"])
        if item is None:
            session.add(ObjectTagDefinition(**row))
        elif item.name == item.code and not item.description:
            item.name = row["name"]
            item.description = row.get("description")
    session.flush()
