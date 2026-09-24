"""Idempotency of versioned CORE data on an isolated PostgreSQL database."""

import asyncio
import os

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_database_engine
from app.scripts.seed_core import seed_core
from seed.import_object_types import load_object_types

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

        engine = create_database_engine(get_settings())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE object_types SET name = 'Временное имя' WHERE code = 'BUILDING'")
                )
        finally:
            await engine.dispose()
        await seed_core()
        assert await counts() == first
        expected_name = next(
            row["name"] for row in load_object_types() if row["code"] == "BUILDING"
        )
        engine = create_database_engine(get_settings())
        try:
            async with engine.connect() as connection:
                restored = await connection.scalar(
                    text("SELECT name FROM object_types WHERE code = 'BUILDING'")
                )
                assert restored == expected_name
        finally:
            await engine.dispose()

    asyncio.run(run())
