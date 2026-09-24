"""Импорт обязательных справочников из версионированных источников."""

import asyncio

from scripts.import_city_objects.import_objects import load_seed as load_city_objects
from seed.incident_classifier.import_seed import import_seed as import_classifier
from seed.incident_classifier.import_seed import load_seed as load_classifier_data


async def seed_core() -> None:
    """Импортирует классификатор, службы, типы и реестр объектов по FK-порядку."""
    data = load_classifier_data()
    print(f"classifier: {await import_classifier(data)}")
    await load_city_objects()
    print("object registry: imported")


def main() -> None:
    asyncio.run(seed_core())


if __name__ == "__main__":
    main()
