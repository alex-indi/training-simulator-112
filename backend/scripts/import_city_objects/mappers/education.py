"""Dataset 747: официальные названия и классификация по полям источника."""

from app.modules.object_registry.address import normalize_address

SOURCE = "data.mos.ru:747"


def clean(value: object) -> str:
    """Убирает краевые служебные пробелы, сохраняя текст источника внутри строки."""
    return str(value or "").replace("\u00a0", " ").strip()


def classify(kind: str, subtype: str) -> tuple[str, bool]:
    text = f"{kind} {subtype}".lower()
    if "детский сад" in text and ("школа" in text or "гимназия" in text):
        return "EDUCATIONAL_COMPLEX", False
    if "дошкольн" in kind.lower() or "детский сад" in subtype.lower():
        return "KINDERGARTEN", False
    if "общеобразовательн" in kind.lower() or any(
        word in subtype.lower() for word in ("школа", "гимназия", "лицей")
    ):
        return "SCHOOL", False
    return "EDUCATION_UNKNOWN", True


def map_education(row: dict) -> dict:
    cells = row["Cells"]
    external_id = clean(row.get("global_id") or cells.get("global_id"))
    name = clean(cells.get("poln_name"))
    if not external_id or not name:
        raise ValueError("Dataset 747: отсутствует global_id или poln_name")
    kind = clean(cells.get("tipe_uchrezhden"))
    subtype = clean(cells.get("vid_uchrezhdeniya"))
    type_code, needs_review = classify(kind, subtype)
    attributes = {
        "institution_type": kind,
        "institution_subtype": subtype,
        "department": clean(cells.get("podchinenie")),
        "needs_review": needs_review,
    }
    tags = ["education"]
    if type_code in {"SCHOOL", "KINDERGARTEN", "EDUCATIONAL_COMPLEX"}:
        tags.extend(["children", "mass_people"])
    return {
        "source": SOURCE,
        "source_dataset_id": "747",
        "external_id": external_id,
        "name": name,
        "object_type_code": type_code,
        "address": normalize_address(cells.get("yuridich_adress"), default_city="г. Москва"),
        "district": None,
        "administrative_area": None,
        "latitude": None,
        "longitude": None,
        "attributes": attributes,
        "tags": tags,
    }
