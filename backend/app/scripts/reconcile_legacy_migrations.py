"""Переносит историю миграций старой UT112-24.3 без удаления данных.

Запуск из backend: python -m app.scripts.reconcile_legacy_migrations [--apply]
Без --apply команда только проверяет состояние.
"""

import argparse
import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_database_engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LEGACY_REVISION = "20260924_10"
COMMON_REVISION = "20260923_09"
LEGACY_TABLES = (
    "incident_classifier_rules",
    "incident_features",
    "dispatch_services",
    "incident_rule_features",
    "incident_rule_services",
    "object_types",
    "city_objects",
    "object_attributes",
    "object_tags",
)


async def inspect_and_reconcile(*, apply: bool) -> None:
    engine = create_database_engine(get_settings())
    try:
        async with engine.begin() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != LEGACY_REVISION:
                raise RuntimeError(
                    f"Ожидалась старая UT112-24.3 с revision {LEGACY_REVISION}; "
                    f"фактическая revision: {revision}"
                )
            missing = [
                table
                for table in LEGACY_TABLES
                if await connection.scalar(
                    text("SELECT to_regclass(:name)"), {"name": table}
                ) is None
            ]
            if missing:
                raise RuntimeError(f"Старая схема неполная: отсутствуют {', '.join(missing)}")
            main_control_exists = await connection.scalar(
                text("SELECT to_regclass('instructor_actions')")
            )
            if main_control_exists is not None:
                raise RuntimeError(
                    "Обнаружены таблицы актуального main при старой revision; "
                    "автоматическое исправление неоднозначно"
                )
            if apply:
                result = await connection.execute(
                    text("""
                        UPDATE alembic_version SET version_num = :common
                        WHERE version_num = :legacy
                    """),
                    {"common": COMMON_REVISION, "legacy": LEGACY_REVISION},
                )
                if result.rowcount != 1:
                    raise RuntimeError("История миграций изменилась во время проверки")
        print("Проверена старая схема UT112-24.3; данные не удалялись.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="исправить историю и применить head")
    args = parser.parse_args()
    try:
        asyncio.run(inspect_and_reconcile(apply=args.apply))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    if not args.apply:
        print("Для переноса запустите команду повторно с --apply.")
        return
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")
    print("История миграций перенесена на актуальный head.")


if __name__ == "__main__":
    main()
