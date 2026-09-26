"""Нормализация адреса объекта для реестра и карточек."""

import re

_POSTAL_PREFIX = re.compile(r'^(?:["«]\s*)?(?:\d{3}\s?\d{3}|\d{7})(?=\D|$)[\s,.;]*')
_COUNTRY_PREFIX = re.compile(r"^(?:Российская Федерация|Россия)\s*,\s*", re.IGNORECASE)
_CITY_START = re.compile(r"^(?:г\.?\s*|город\s+)?(?:Москва|Москвы)\b", re.IGNORECASE)
_LOCALITY_IN_REGION = re.compile(
    r"(?:^|,\s*)((?:г\.?\s*|город\s+|поселок\s+|посёлок\s+|пос\.\s*|п\.\s*|деревня\s+|село\s+|с\.\s*)[А-ЯЁ])",
    re.IGNORECASE,
)
_POSTAL_IN_TEXT = re.compile(
    r'(?<!\d)(?:["«]\s*)?(?:\d{3}\s?\d{3}|\d{7})(?=\D|$)[\s,.;]*'
    r"(?=(?:г\.?\s*|город\s+)?(?:Москва|Москвы|Московская область)\b)",
    re.IGNORECASE,
)


def normalize_address(value: object, *, default_city: str | None = None) -> str | None:
    """Удаляет начальный индекс и служебный префикс, сохраняя остальные части адреса."""
    address = str(value or "").replace("\u00a0", " ").strip()
    while match := _POSTAL_PREFIX.match(address):
        address = address[match.end() :].lstrip()
    if address in {"", "0"}:
        return None
    address = _COUNTRY_PREFIX.sub("", address)
    address = re.sub(r"^город\s+\.\s*Москва\b", "город Москва", address, flags=re.IGNORECASE)
    if address.startswith("Московская область,"):
        locality = _LOCALITY_IN_REGION.search(address)
        if locality:
            address = address[locality.start(1) :]
    if default_city and not _CITY_START.match(address) and not address.startswith(
        ("Московская область", "г.", "город ", "поселок ", "посёлок ", "деревня ", "село ")
    ):
        address = f"{default_city}, {address}"
    return address


def normalize_generated_text(text: str, old_address: str, new_address: str) -> str:
    """Убирает индекс из ранее сформированного текста, не меняя другие числа."""
    text = text.replace(old_address, new_address)
    return _POSTAL_IN_TEXT.sub("", text)
