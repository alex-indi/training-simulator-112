"""Idempotency of versioned CORE data on an isolated PostgreSQL database."""

import asyncio
import os

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_database_engine
from app.scripts.seed_core import seed_core

TABLES = (
    "incident_classifier_rules",
    "incident_features",
    "incident_rule_features",
    "dispatch_services",
    "incident_rule_services",
    "object_types",
    "city_objects",
    "object_attributes",
    "object_tags",
)


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1", reason="Requires isolated migrated PostgreSQL database"
)
def test_seed_core_twice_keeps_counts() -> None:
    async def counts() -> dict[str, int]:
        engine = create_database_engine(get_settings())
        try:
            async with engine.connect() as connection:
                return {
                    table: (await connection.scalar(text(f"SELECT count(*) FROM {table}"))) or 0
                    for table in TABLES
                }
        finally:
            await engine.dispose()

    async def run() -> None:
        await seed_core()
        first = await counts()
        assert all(first.values())
        await seed_core()
        assert await counts() == first

    asyncio.run(run())
