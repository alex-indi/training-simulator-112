"""Read-only database diagnostics used by the local launcher."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_database_engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_TABLES = {
    "users": "users",
    "classifier rules": "incident_classifier_rules",
    "dispatch services": "dispatch_services",
    "object types": "object_types",
}


async def inspect_database(include_references: bool) -> dict[str, object]:
    """Check connectivity, the single Alembic head, and essential small tables."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one Alembic head, found {len(heads)}")

    engine = create_database_engine(get_settings())
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            def current_revisions(sync_connection):
                context = MigrationContext.configure(sync_connection)
                return context.get_current_heads()

            current_heads = await connection.run_sync(current_revisions)
            current = current_heads[0] if len(current_heads) == 1 else ", ".join(current_heads)
            result: dict[str, object] = {"current": current, "head": heads[0]}
            if include_references:
                missing = []
                for label, table in REQUIRED_TABLES.items():
                    exists = await connection.scalar(
                        text("SELECT to_regclass(:name)"), {"name": table}
                    )
                    if exists is None or not await connection.scalar(
                        text(f"SELECT EXISTS (SELECT 1 FROM {table})")
                    ):
                        missing.append(label)
                result["missing_references"] = missing
            return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--references", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(inspect_database(args.references))))


if __name__ == "__main__":
    main()
