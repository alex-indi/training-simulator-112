"""Импорт проверенного JSON seed после извлечения данных из источников заказчика.

Запуск: cd backend && uv run python -m seed.incident_classifier.import_seed
Пустой seed и любые неизвестные ссылки завершаются ошибкой до записи в БД.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.modules.incident_classifier.models import (
    DispatchService,
    IncidentClassifierRule,
    IncidentFeature,
    IncidentRuleFeature,
    IncidentRuleService,
)
from seed.import_object_tag_classifier_features import load_links, upsert_links

ROOT = Path(__file__).resolve().parents[1]


def load_seed(root: Path = ROOT) -> dict[str, list[dict]]:
    files = {
        "rules": root / "incident_classifier/rules.json",
        "features": root / "incident_classifier/features.json",
        "rule_features": root / "incident_classifier/rule_features.json",
        "rule_services": root / "incident_classifier/rule_services.json",
        "services": root / "services/services.json",
    }
    data = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in files.items()}
    if not all(isinstance(rows, list) for rows in data.values()):
        raise ValueError("Все файлы seed должны содержать JSON-массивы")
    if not data["rules"] or not data["services"]:
        raise ValueError("Нет проверенных данных SRC-006 или каталога служб")
    keys = {
        "rules": "source_reference",
        "features": "source_column",  # проверяются составным ключом ниже
        "services": "source_reference",
    }
    for name, field in keys.items():
        if name == "features":
            values = [
                (row["level"], row["source_column"], row["source_value"]) for row in data[name]
            ]
        else:
            values = [row[field] for row in data[name]]
        if any(not value for value in values) or len(values) != len(set(values)):
            raise ValueError(f"Пустые или повторяющиеся ключи в {name}")
    rule_refs = {row["source_reference"] for row in data["rules"]}
    feature_keys = {
        (row["level"], row["source_column"], row["source_value"]) for row in data["features"]
    }
    service_refs = {row["source_reference"] for row in data["services"]}
    for link in data["rule_features"]:
        if (
            link["rule_source_reference"] not in rule_refs
            or tuple(link["feature_key"]) not in feature_keys
        ):
            raise ValueError(f"Неизвестная связь правила и признака: {link}")
    for link in data["rule_services"]:
        if (
            link["rule_source_reference"] not in rule_refs
            or link["service_source_reference"] not in service_refs
            or not link.get("source_reference")
        ):
            raise ValueError(f"Неизвестная или неподтверждённая связь службы: {link}")
    for name, columns in (
        ("rule_features", ("rule_source_reference", "feature_key")),
        ("rule_services", ("rule_source_reference", "service_source_reference")),
    ):
        pairs = [
            (
                row[columns[0]],
                tuple(row[columns[1]]) if isinstance(row[columns[1]], list) else row[columns[1]],
            )
            for row in data[name]
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError(f"Повторяющиеся связи в {name}")
    return data


async def import_seed(data: dict[str, list[dict]]) -> dict[str, int]:
    engine = create_database_engine(get_settings())
    factory = create_session_factory(engine)
    try:
        async with factory.begin() as session:
            rules = {
                row.source_reference: row
                for row in (await session.scalars(select(IncidentClassifierRule))).all()
            }
            features = {
                (row.level, row.source_column, row.source_value): row
                for row in (await session.scalars(select(IncidentFeature))).all()
            }
            services = {
                row.source_reference: row
                for row in (await session.scalars(select(DispatchService))).all()
            }
            for row in data["rules"]:
                key = row["source_reference"]
                item = rules.setdefault(key, IncidentClassifierRule(source_reference=key))
                for field in ("source_code", "incident_group", "final_incident_type", "ekp35_type"):
                    setattr(item, field, row.get(field))
                session.add(item)
            for row in data["features"]:
                key = (row["level"], row["source_column"], row["source_value"])
                item = features.setdefault(key, IncidentFeature(**row))
                item.name = row["name"]
                session.add(item)
            for row in data["services"]:
                key = row["source_reference"]
                item = services.setdefault(key, DispatchService(source_reference=key))
                for field in ("official_name", "organization", "service_level"):
                    setattr(item, field, row.get(field))
                session.add(item)
            await session.flush()
            existing_features = {
                (row.rule_id, row.feature_id)
                for row in (await session.scalars(select(IncidentRuleFeature))).all()
            }
            existing_services = {
                (row.rule_id, row.service_id): row
                for row in (await session.scalars(select(IncidentRuleService))).all()
            }
            for link in data["rule_features"]:
                pair = (
                    rules[link["rule_source_reference"]].id,
                    features[tuple(link["feature_key"])].id,
                )
                if pair not in existing_features:
                    session.add(IncidentRuleFeature(rule_id=pair[0], feature_id=pair[1]))
                    existing_features.add(pair)
            for link in data["rule_services"]:
                pair = (
                    rules[link["rule_source_reference"]].id,
                    services[link["service_source_reference"]].id,
                )
                item = existing_services.get(pair)
                if item is None:
                    item = IncidentRuleService(rule_id=pair[0], service_id=pair[1])
                    session.add(item)
                    existing_services[pair] = item
                item.source_reference = link["source_reference"]
            await session.run_sync(upsert_links, load_links())
        return {name: len(rows) for name, rows in data.items()}
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(asyncio.run(import_seed(load_seed())))
