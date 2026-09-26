"""Применяет миграции перед локальным запуском, включая известную старую ветку."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.db.session import create_database_engine
from app.scripts.reconcile_legacy_migrations import inspect_and_reconcile

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SCENARIO_REVISION = "20260924_18"
COMMON_REVISION = "20260923_09"
CONTROL_REVISION = "20260924_12"

REQUIRED_LEGACY_TABLES = {
    "incident_classifier_rules",
    "incident_features",
    "dispatch_services",
    "incident_rule_features",
    "incident_rule_services",
    "object_types",
    "city_objects",
    "object_attributes",
    "object_tags",
    "object_tags_dictionary",
    "object_tag_classifier_features",
    "scenario_templates",
    "scenario_template_object_rules",
    "scenario_template_required_object_tags",
    "scenario_event_templates",
    "scenario_template_services",
    "scenario_expected_actions",
    "scenario_assessment_criteria",
}
CONTROL_TABLES = {
    "instructor_actions",
    "session_pauses",
    "run_pauses",
    "instructor_notes",
    "scenario_events",
    "assessment_results",
    "assessment_deviations",
    "assessment_audit",
}


async def detect_legacy_revision() -> str | None:
    """Возвращает известную старую revision или останавливает неоднозначный случай."""
    engine = create_database_engine(get_settings())
    try:
        async with engine.connect() as connection:
            if await connection.scalar(text("SELECT to_regclass('alembic_version')")) is None:
                return None
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision == "20260924_10":
                return revision
            if revision != LEGACY_SCENARIO_REVISION:
                return None

            def inspect_schema(sync_connection):
                inspector = inspect(sync_connection)
                tables = set(inspector.get_table_names())
                columns = {
                    name: {column["name"] for column in inspector.get_columns(name)}
                    for name in (
                        "training_sessions", "training_runs", "response_units", "scenario_templates"
                    )
                }
                return tables, columns

            tables, columns = await connection.run_sync(inspect_schema)
            session_control_columns = {
                "paused_at", "paused_seconds", "finish_mode", "completed_at"
            }
            run_control_columns = {"paused_at", "paused_seconds"}
            if (
                CONTROL_TABLES <= tables
                and session_control_columns <= columns["training_sessions"]
                and run_control_columns <= columns["training_runs"]
                and "seed_code" in columns["response_units"]
                and "seed_code" in columns["scenario_templates"]
            ):
                return None
            if (
                not REQUIRED_LEGACY_TABLES <= tables
                or CONTROL_TABLES & tables
                or session_control_columns & columns["training_sessions"]
                or run_control_columns & columns["training_runs"]
                or "seed_code" in columns["response_units"]
                or "seed_code" not in columns["scenario_templates"]
            ):
                raise RuntimeError(
                    "Ревизия 20260924_18 не совпадает с известной старой схемой; "
                    "миграции остановлены для сохранения данных"
                )
            return revision
    finally:
        await engine.dispose()


def alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return config


async def restore_skipped_control_migrations(config: Config) -> None:
    """Возвращает пропущенные DDL и запись Alembic одной транзакцией."""
    engine = create_database_engine(get_settings())
    try:
        async with engine.begin() as connection:
            def restore(sync_connection) -> None:
                config.attributes["connection"] = sync_connection
                command.stamp(config, COMMON_REVISION)
                command.upgrade(config, CONTROL_REVISION)
                command.stamp(config, LEGACY_SCENARIO_REVISION)

            await connection.run_sync(restore)
    finally:
        config.attributes.pop("connection", None)
        await engine.dispose()


def main() -> None:
    revision = asyncio.run(detect_legacy_revision())
    config = alembic_config()
    if revision == "20260924_10":
        asyncio.run(inspect_and_reconcile(apply=True))
    elif revision == LEGACY_SCENARIO_REVISION:
        print("[db] Восстанавливаю пропущенные миграции управления занятием...", flush=True)
        asyncio.run(restore_skipped_control_migrations(config))
    command.upgrade(config, "head")
    print("[db] Миграции применены.", flush=True)


if __name__ == "__main__":
    main()
