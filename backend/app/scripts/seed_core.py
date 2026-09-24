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

    await classifier.import_seed(classifier.load_seed())
    raise CoreSeedUnavailableError(
        "Object Registry отсутствует в текущей ветке. "
        "Добавьте его версионированный импорт после объединения UT112-24.3."
    )


def main() -> None:
    asyncio.run(seed_core())


if __name__ == "__main__":
    main()
