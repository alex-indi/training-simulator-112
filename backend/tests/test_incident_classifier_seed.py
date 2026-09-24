"""Целостность подготовленного справочника и прослеживаемость источников."""

from copy import deepcopy

import pytest

from seed.incident_classifier.import_seed import load_seed


def test_seed_has_traced_rules_features_services_and_links() -> None:
    data = load_seed()
    assert len(data["rules"]) == 1283
    assert len(data["features"]) == 1024
    assert len(data["services"]) == 209
    assert len(data["rule_features"]) == 2816
    assert len(data["rule_services"]) == 1179
    assert all(".xlsx#Лист1!" in row["source_reference"] for row in data["rules"])
    assert all(".docx#word/media/image" in row["source_reference"] for row in data["services"])
    assert all(".xlsx#Лист1!M" in row["source_reference"] for row in data["rule_services"])


def test_seed_rejects_unknown_service_link(tmp_path) -> None:
    data = deepcopy(load_seed())
    data["rule_services"][0]["service_source_reference"] = "invented-service"
    folders = [tmp_path / "incident_classifier", tmp_path / "services"]
    for folder in folders:
        folder.mkdir()
    import json

    for name in ("rules", "features", "rule_features", "rule_services"):
        (folders[0] / f"{name}.json").write_text(json.dumps(data[name]))
    (folders[1] / "services.json").write_text(json.dumps(data["services"]))
    with pytest.raises(ValueError, match="Неизвестная или неподтверждённая связь"):
        load_seed(tmp_path)
