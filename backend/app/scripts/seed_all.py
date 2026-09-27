"""Последовательно загружает CORE и полный демонстрационный стенд."""

import asyncio

from app.scripts.seed_core import seed_core
from app.scripts.seed_demo import seed_demo
from app.scripts.seed_demo_content import seed_demo_content
from app.scripts.seed_demo_history import seed_demo_history
from seed.scenario_templates.import_seed import import_seed as import_scenarios


async def seed_all() -> None:
    await seed_core()
    for name, stats in (await seed_demo()).items():
        print(f"{name}: {stats}")
    print(f"scenario_templates: {await import_scenarios()}")
    for name, stats in (await seed_demo_content()).items():
        print(f"{name}: {stats}")
    print(f"completed_sessions: {await seed_demo_history()}")


if __name__ == "__main__":
    asyncio.run(seed_all())
