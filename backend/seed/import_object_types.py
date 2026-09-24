"""Идемпотентная загрузка стартового дерева типов объектов.

Запуск: cd backend && uv run python -m seed.import_object_types
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.modules.object_registry.models import ObjectType

SEED_PATH = Path(__file__).with_name("object_types.json")


def load_object_types(path: Path = SEED_PATH) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Seed типов должен быть непустым массивом")
    codes: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or any(
            not row.get(field) for field in ("code", "name", "source")
        ):
            raise ValueError("У каждого типа нужны code, name и source")
        if row["code"] in codes:
            raise ValueError(f"Повторяющийся код типа: {row['code']}")
        if row.get("parent_code") is not None and row["parent_code"] not in codes:
            raise ValueError(f"Родитель должен предшествовать типу: {row['code']}")
        codes.add(row["code"])
    return rows


async def upsert_object_types(session: AsyncSession, rows: list[dict]) -> None:
    """Добавляет отсутствующие типы; существующие пользовательские записи не изменяет."""

    existing = {row.code: row for row in (await session.scalars(select(ObjectType))).all()}
    for row in rows:
        if row["code"] in existing:
            continue
        parent_code = row.get("parent_code")
        if parent_code is not None and parent_code not in existing:
            raise ValueError(f"Неизвестный родитель: {parent_code}")
        item = ObjectType(
            code=row["code"],
            name=row["name"],
            parent_id=existing[parent_code].id if parent_code else None,
            description=row.get("description"),
            source=row["source"],
        )
        session.add(item)
        await session.flush()
        existing[item.code] = item


async def import_object_types() -> None:
    rows = load_object_types()
    engine = create_database_engine(get_settings())
    factory = create_session_factory(engine)
    try:
        async with factory.begin() as session:
            await upsert_object_types(session, rows)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(import_object_types())
