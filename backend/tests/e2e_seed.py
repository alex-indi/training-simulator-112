"""Seed a second demo trainee in an isolated E2E database only."""

import asyncio
import os

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_database_engine


async def main() -> None:
    if os.getenv("E2E_SEED") != "1":
        raise RuntimeError("Set E2E_SEED=1 for the isolated E2E database")
    engine = create_database_engine(get_settings())
    async with engine.begin() as connection:
        await connection.execute(text("""
            INSERT INTO users (id, username, full_name, role, is_active)
            VALUES (1900000000, 'trainee2', 'Второй обучаемый', 'TRAINEE', true)
            ON CONFLICT (username) DO NOTHING
        """))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
