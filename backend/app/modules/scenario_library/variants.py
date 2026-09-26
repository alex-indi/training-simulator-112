"""Reproducible, bounded variation of prepared scenario cards."""

from __future__ import annotations

import random

SCHOOL_FIRE_CODE = "DEMO_EDUCATION_FIRE_001"
SCHOOL_FIRE_MEDICAL_SOURCE = "СЛУЖБЫ 112.docx#word/media/image1.png/row-04"

SCHOOL_FIRE_OPTIONS = {
    "floor": (1, 2, 3),
    "room": ("коридор", "кабинет", "подсобное помещение"),
    "observation": ("запах гари", "задымление", "сильное задымление"),
    "casualties": ("пострадавшие неизвестны", "пострадавших нет", "один пострадавший"),
}


def variant_facts(
    seed_code: str | None, seed: int, options: dict[str, list[str | int]] | None = None
) -> dict[str, object]:
    """Choose only facts explicitly allowed by the methodical template."""
    choices = options or (SCHOOL_FIRE_OPTIONS if seed_code == SCHOOL_FIRE_CODE else {})
    rng = random.Random(seed)
    return {key: rng.choice(values) for key, values in choices.items() if values}


def render_variant_text(text: str, facts: dict[str, object]) -> str:
    """Substitute only facts selected from the template's allowed choices."""
    for key, value in facts.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def card_seeds(seed: int, count: int) -> list[int]:
    """Stable distinct seeds within the database's signed integer range."""
    rng = random.Random(seed)
    return rng.sample(range(0, 2_147_483_648), count)


def object_order(object_ids: list[int], seed: int) -> list[int]:
    result = list(object_ids)
    random.Random(seed).shuffle(result)
    return result
