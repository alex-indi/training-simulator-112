"""Повторная выгрузка исходных наборов data.mos.ru для разработки mapper-ов.

Запуск: cd backend && MOS_API_KEY=... uv run python -m seed.object_registry.temp_import_mos_objects
Ключ передаётся только через окружение и не записывается в репозиторий.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_URL = "https://apidata.mos.ru/v1"
OUTPUT_DIR = Path(__file__).with_name("source_data")
DATASETS = {"schools": 747, "metro": 624}


def api_get(path: str, *, api_key: str, params: dict[str, int] | None = None):
    query = {**(params or {}), "api_key": api_key}
    url = f"{BASE_URL}/{path}?{urlencode(query)}"
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


def save_json(filename: str, data: object) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / filename).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    api_key = os.getenv("MOS_API_KEY")
    if not api_key:
        raise RuntimeError("Для повторной выгрузки установите MOS_API_KEY")
    report = {}
    for name, dataset_id in DATASETS.items():
        info = api_get(f"datasets/{dataset_id}", api_key=api_key)
        rows = get_rows(dataset_id, api_key=api_key)
        save_json(f"{name}_dataset_info.json", info)
        save_json(f"{name}_raw_rows.json", rows)
        report[name] = {"dataset_id": dataset_id, "count": len(rows)}
        print(f"{name}: {len(rows)} записей")
    save_json("import_report.json", report)


if __name__ == "__main__":
    main()
