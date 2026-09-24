"""Подготавливает чистую PostgreSQL миграциями и версионированными seed."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import check_database_connection, create_database_engine
from app.scripts.seed_all import seed_all
from app.scripts.seed_core import CoreSeedUnavailableError

BACKEND_ROOT = Path(__file__).resolve().parents[2]


async def check_connection() -> None:
    engine = create_database_engine(get_settings())
    try:
        await check_database_connection(engine)
    finally:
        await engine.dispose()


async def integrity_check() -> dict[str, int]:
    """Считает фактические записи и требует все обязательные CORE-таблицы."""
    required = {
        "classifier_rules": "incident_classifier_rules",
        "services": "dispatch_services",
        "object_types": "object_types",
        "city_objects": "city_objects",
    }
    engine = create_database_engine(get_settings())
    try:
        async with engine.connect() as connection:
            counts: dict[str, int] = {}
            for label, table in required.items():
                exists = await connection.scalar(
                    text("SELECT to_regclass(:table_name)"), {"table_name": table}
                )
                if exists is None:
                    raise RuntimeError(f"Отсутствует обязательная таблица {table}")
                count = await connection.scalar(text(f"SELECT count(*) FROM {table}"))
                if not count:
                    raise RuntimeError(f"Обязательный справочник {table} пуст")
                counts[label] = count
            for label, table in (
                ("demo_users", "users"),
                ("response_units", "response_units"),
            ):
                counts[label] = await connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0
            return counts
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(check_connection())
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")
    try:
        asyncio.run(seed_all())
    except CoreSeedUnavailableError as exc:
        raise SystemExit(str(exc)) from None
    counts = asyncio.run(integrity_check())
    print("Database bootstrap completed")
    for label, count in counts.items():
        print(f"{label}: {count}")
    print("Database is ready.")


if __name__ == "__main__":
    main()
