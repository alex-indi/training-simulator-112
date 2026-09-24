"""Проверка версионированного DEMO seed на изолированной PostgreSQL."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_database_engine
from app.scripts.seed_demo import load_rows, seed_demo


def test_demo_seed_files_have_unique_stable_keys() -> None:
    assert load_rows("users.json", "username")
    assert load_rows("response_units.json", "seed_code")


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1", reason="Requires isolated PostgreSQL test database"
)
def test_demo_seed_is_idempotent_updates_records_and_preserves_runtime() -> None:
    async def run() -> None:
        engine = create_database_engine(get_settings())
        title = f"Seed runtime preservation {uuid4().hex}"
        session_id = None
        try:
            await seed_demo()
            async with engine.begin() as connection:
                instructor_id = await connection.scalar(
                    text("SELECT id FROM users WHERE username = 'instructor'")
                )
                session_id = await connection.scalar(
                    text("""
                        INSERT INTO training_sessions (title, instructor_id)
                        VALUES (:title, :instructor_id) RETURNING id
                    """),
                    {"title": title, "instructor_id": instructor_id},
                )
                await connection.execute(
                    text("""
                        UPDATE response_units SET name = 'Временное имя'
                        WHERE seed_code = 'DEMO_DDS_UNIT_01'
                    """)
                )

            first = await seed_demo()
            second = await seed_demo()
            assert first["response_units"] == {"created": 0, "updated": 1, "unchanged": 0}
            assert second["response_units"] == {"created": 0, "updated": 0, "unchanged": 1}
            async with engine.connect() as connection:
                assert await connection.scalar(
                    text("SELECT count(*) FROM response_units WHERE seed_code = 'DEMO_DDS_UNIT_01'")
                ) == 1
                assert await connection.scalar(
                    text("SELECT count(*) FROM training_sessions WHERE id = :id"),
                    {"id": session_id},
                ) == 1
        finally:
            if session_id is not None:
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM training_sessions WHERE id = :id"), {"id": session_id}
                    )
            await engine.dispose()

    asyncio.run(run())
