"""Выгрузка исходных наборов data.mos.ru; ключ остаётся в окружении."""

import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_URL = "https://apidata.mos.ru/v1"
DATASETS = {"schools": 747, "metro": 624}
SOURCE_DIR = Path(__file__).resolve().parents[2] / "seed/object_registry/source_data"


def api_get(path: str, *, api_key: str, params: dict[str, int] | None = None):
    url = f"{BASE_URL}/{path}?{urlencode({**(params or {}), 'api_key': api_key})}"
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def get_rows(dataset_id: int, *, api_key: str, limit: int = 1000) -> list[dict]:
    rows: list[dict] = []
    skip = 0
    while True:
        page = api_get(
            f"datasets/{dataset_id}/rows",
            api_key=api_key,
            params={"$top": limit, "$skip": skip},
        )
        rows.extend(page)
        if len(page) < limit:
            return rows
        skip += limit


def refresh_sources() -> None:
    api_key = os.getenv("MOS_API_KEY")
    if not api_key:
        raise RuntimeError("Для обновления выгрузок установите MOS_API_KEY")
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, dataset_id in DATASETS.items():
        info = api_get(f"datasets/{dataset_id}", api_key=api_key)
        rows = get_rows(dataset_id, api_key=api_key)
        for suffix, data in (("dataset_info", info), ("raw_rows", rows)):
            (SOURCE_DIR / f"{name}_{suffix}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        report[name] = {"dataset_id": dataset_id, "count": len(rows)}
        print(f"{name}: {len(rows)} записей")
    (SOURCE_DIR / "import_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    refresh_sources()
