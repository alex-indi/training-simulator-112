"""Последовательно загружает CORE и DEMO без runtime-истории."""

import asyncio

from app.scripts.seed_core import CoreSeedUnavailableError, seed_core
from app.scripts.seed_demo import seed_demo


async def seed_all() -> None:
    await seed_core()
    for name, stats in (await seed_demo()).items():
        print(f"{name}: {stats}")


if __name__ == "__main__":
    try:
        asyncio.run(seed_all())
    except CoreSeedUnavailableError as exc:
        raise SystemExit(str(exc)) from None
