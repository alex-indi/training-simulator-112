"""Последовательно загружает CORE и DEMO без runtime-истории."""

import asyncio

from app.scripts.seed_core import seed_core
from app.scripts.seed_demo import seed_demo
from seed.scenario_templates.import_seed import import_seed as import_scenarios


async def seed_all() -> None:
    await seed_core()
    for name, stats in (await seed_demo()).items():
        print(f"{name}: {stats}")
    print(f"scenario_templates: {await import_scenarios()}")


if __name__ == "__main__":
    asyncio.run(seed_all())
