"""Load manually verified links between object tags and SRC-006 features."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.incident_classifier.models import IncidentFeature
from app.modules.object_registry.models import ObjectTagClassifierFeature, ObjectTagDefinition

SEED_PATH = Path(__file__).with_name("object_tag_classifier_features.json")


def load_links(path: Path = SEED_PATH) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    keys = [(row["tag_code"], tuple(row["feature_key"])) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Повторяющиеся связи тегов и SRC-006")
    return rows


def upsert_links(session: Session, rows: list[dict]) -> None:
    """Add links after both seeds exist; reject incomplete classifier data."""
    tags = set(session.scalars(select(ObjectTagDefinition.code)))
    features = {
        (row.level, row.source_column, row.source_value): row.id
        for row in session.scalars(select(IncidentFeature))
    }
    if not tags or not features:
        return
    existing = {
        (row.tag_code, row.feature_id)
        for row in session.scalars(select(ObjectTagClassifierFeature))
    }
    for row in rows:
        tag_code = row["tag_code"]
        feature_key = tuple(row["feature_key"])
        if tag_code not in tags or feature_key not in features:
            raise ValueError(f"Неизвестная связь тега и SRC-006: {tag_code}, {feature_key}")
        pair = (tag_code, features[feature_key])
        if pair not in existing:
            session.add(ObjectTagClassifierFeature(tag_code=pair[0], feature_id=pair[1]))
            existing.add(pair)
    session.flush()
