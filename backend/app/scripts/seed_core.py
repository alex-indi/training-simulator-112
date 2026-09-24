"""Импорт обязательных справочников из версионированных источников."""

import asyncio
from importlib import import_module


class CoreSeedUnavailableError(RuntimeError):
    """Обязательные источники ещё не присутствуют в текущей ветке."""


async def seed_core() -> None:
    """Импортирует CORE в порядке зависимостей после появления доменных модулей."""
    try:
        classifier = import_module("seed.incident_classifier.import_seed")
    except ModuleNotFoundError as exc:
        if exc.name not in {"seed", "seed.incident_classifier"}:
            raise
        raise CoreSeedUnavailableError(
            "SRC-006 отсутствует в текущей ветке. Сначала объедините UT112-24.1."
        ) from exc

    try:
        registry = import_module("seed.object_registry.import_seed")
    except ModuleNotFoundError as exc:
        if exc.name not in {"seed.object_registry", "seed.object_registry.import_seed"}:
            raise
        raise CoreSeedUnavailableError(
            "Импорт Object Registry ещё не реализован в текущей ветке. "
            "Сначала совместите UT112-24.3 с актуальным main."
        ) from exc

    await classifier.import_seed(classifier.load_seed())
    await registry.import_seed(registry.load_seed())


def main() -> None:
    try:
        asyncio.run(seed_core())
    except CoreSeedUnavailableError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
