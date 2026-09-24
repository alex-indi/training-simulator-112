"""Надёжная выгрузка исходных наборов data.mos.ru.

Главное отличие от предыдущей версии:
- используется requests, как в рабочем временном скрипте;
- API-ключ передаётся только как query-параметр api_key;
- есть повторные попытки для 429/5xx;
- увеличен тайм-аут чтения;
- ошибки показывают код и тело ответа, но не раскрывают API-ключ.

Запуск из backend/:
    uv run python -m scripts.import_city_objects.mos_api_client check 747
    uv run python -m scripts.import_city_objects.mos_api_client fetch 502 hospitals_children
    uv run python -m scripts.import_city_objects.mos_api_client fetch 503 polyclinics_adults
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://apidata.mos.ru/v1"

# Эти наборы используются только командой refresh-existing.
# Произвольный dataset_id можно всегда выгрузить через команду fetch.
DATASETS = {
    "schools": 747,
    "metro": 624,
    "hospitals_children": 502,
    "polyclinics_adults": 503,
    "polyclinics_children": 505,
    "emergency_stations": 516,
    "hospitals_adults": 517,
}

SOURCE_DIR = Path(__file__).resolve().parents[2] / "seed/object_registry/source_data"
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def get_api_key() -> str:
    """Получить ключ из переменной окружения или корневого .env."""
    key = os.getenv("MOS_API_KEY") or dotenv_values(ENV_FILE).get("MOS_API_KEY")
    if not key:
        raise RuntimeError(
            f"MOS_API_KEY не найден. "
            f"Укажите его в переменной окружения или в {ENV_FILE}"
        )
    return str(key).strip()


def make_session() -> requests.Session:
    """Создать HTTP-сессию с повторными попытками для временных ошибок API."""
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)

    session = requests.Session()
    session.mount("https://", adapter)
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "training-simulator-112/1.0",
        }
    )
    return session


def api_get(
    path: str,
    *,
    api_key: str,
    params: dict[str, Any] | None = None,
    timeout: tuple[int, int] = (10, 60),
    session: requests.Session | None = None,
) -> Any:
    """Выполнить GET к data.mos.ru, не выводя API-ключ в лог."""
    own_session = session is None
    http = session or make_session()

    query = dict(params or {})
    query["api_key"] = api_key

    url = f"{BASE_URL}/{path.lstrip('/')}"

    try:
        response = http.get(url, params=query, timeout=timeout)

        if not response.ok:
            # Ключ намеренно не включаем в диагностическое сообщение.
            body = response.text[:1000].replace(api_key, "<redacted>").strip()
            raise RuntimeError(
                f"data.mos.ru API вернул HTTP {response.status_code} "
                f"для {url}. Ответ: {body or '<пустой ответ>'}"
            )

        try:
            return response.json()
        except ValueError as error:
            body = response.text[:1000].replace(api_key, "<redacted>").strip()
            raise RuntimeError(
                f"data.mos.ru API вернул не JSON для {url}. "
                f"Начало ответа: {body or '<пустой ответ>'}"
            ) from error

    except requests.Timeout as error:
        raise RuntimeError(
            f"Тайм-аут при обращении к data.mos.ru: {url}"
        ) from error
    except requests.ConnectionError as error:
        raise RuntimeError(
            f"Ошибка соединения с data.mos.ru: {url}. "
            f"Причина: {type(error).__name__}"
        ) from error
    finally:
        if own_session:
            http.close()


def get_rows(
    dataset_id: int,
    *,
    api_key: str,
    limit: int = 500,
    timeout: tuple[int, int] = (10, 60),
    pause: float = 0.15,
) -> list[dict]:
    """Постранично выгрузить все строки набора."""
    if not 1 <= limit <= 1000:
        raise ValueError("Размер страницы должен быть от 1 до 1000")

    rows: list[dict] = []
    skip = 0

    with make_session() as session:
        while True:
            page = api_get(
                f"datasets/{dataset_id}/rows",
                api_key=api_key,
                params={
                    "$top": limit,
                    "$skip": skip,
                },
                timeout=timeout,
                session=session,
            )

            if not isinstance(page, list):
                raise RuntimeError(
                    f"Набор {dataset_id}: API вернул страницу "
                    f"в неожиданном формате {type(page).__name__}"
                )

            rows.extend(page)
            print(
                f"dataset {dataset_id}: получено {len(rows)} записей",
                flush=True,
            )

            if len(page) < limit:
                return rows

            skip += limit
            if pause > 0:
                time.sleep(pause)


def _write_json(path: Path, data: object) -> None:
    """Атомарно сохранить JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        temporary.write(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        )
        temporary_path = Path(temporary.name)

    temporary_path.replace(path)


def fetch_dataset(
    dataset_id: int,
    name: str,
    *,
    output_dir: Path = SOURCE_DIR,
    force: bool = False,
    page_size: int = 500,
    connect_timeout: int = 10,
    read_timeout: int = 60,
) -> dict:
    """Выгрузить паспорт и все строки одного набора."""
    if dataset_id <= 0:
        raise ValueError("ID набора должен быть положительным числом")

    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(
            "Имя набора должно содержать только строчные латинские "
            "буквы, цифры и подчёркивание"
        )

    paths = {
        "info": output_dir / f"{name}_dataset_info.json",
        "rows": output_dir / f"{name}_raw_rows.json",
        "report": output_dir / f"{name}_fetch_report.json",
    }

    if not force and any(path.exists() for path in paths.values()):
        raise FileExistsError(
            f"Файлы {name} уже существуют; "
            f"для обновления укажите --force"
        )

    api_key = get_api_key()
    timeout = (connect_timeout, read_timeout)

    with make_session() as session:
        info = api_get(
            f"datasets/{dataset_id}",
            api_key=api_key,
            timeout=timeout,
            session=session,
        )

    rows = get_rows(
        dataset_id,
        api_key=api_key,
        limit=page_size,
        timeout=timeout,
    )

    report = {
        "source": "data.mos.ru",
        "dataset_id": dataset_id,
        "name": name,
        "rows": len(rows),
        "caption": info.get("Caption") if isinstance(info, dict) else None,
    }

    _write_json(paths["info"], info)
    _write_json(paths["rows"], rows)
    _write_json(paths["report"], report)

    return report


def refresh_sources() -> None:
    """Обновить только уже заведённые базовые источники."""
    for name, dataset_id in DATASETS.items():
        report = fetch_dataset(
            dataset_id,
            name,
            force=True,
        )
        print(json.dumps(report, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")

    check = commands.add_parser(
        "check",
        help="Проверить ключ и доступность паспорта набора",
    )
    check.add_argument("dataset_id", type=int)
    check.add_argument("--connect-timeout", type=int, default=10)
    check.add_argument("--read-timeout", type=int, default=60)

    fetch = commands.add_parser(
        "fetch",
        help="Выгрузить паспорт и все строки набора",
    )
    fetch.add_argument("dataset_id", type=int)
    fetch.add_argument(
        "name",
        help="Например hospitals_adults или polyclinics_children",
    )
    fetch.add_argument("--output-dir", type=Path, default=SOURCE_DIR)
    fetch.add_argument("--page-size", type=int, default=500)
    fetch.add_argument("--connect-timeout", type=int, default=10)
    fetch.add_argument("--read-timeout", type=int, default=60)
    fetch.add_argument("--force", action="store_true")

    commands.add_parser(
        "refresh-existing",
        help="Обновить только наборы, перечисленные в DATASETS",
    )

    args = parser.parse_args()

    try:
        if args.command == "check":
            result = api_get(
                f"datasets/{args.dataset_id}",
                api_key=get_api_key(),
                timeout=(args.connect_timeout, args.read_timeout),
            )
            caption = (
                result.get("Caption")
                if isinstance(result, dict)
                else None
            )
            print(
                f"Набор {args.dataset_id} доступен"
                + (f": {caption}" if caption else "")
            )

        elif args.command == "fetch":
            report = fetch_dataset(
                args.dataset_id,
                args.name,
                output_dir=args.output_dir,
                force=args.force,
                page_size=args.page_size,
                connect_timeout=args.connect_timeout,
                read_timeout=args.read_timeout,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))

        elif args.command == "refresh-existing":
            refresh_sources()

        else:
            parser.print_help()

    except (RuntimeError, ValueError, FileExistsError) as error:
        parser.exit(1, f"Ошибка: {error}\n")


if __name__ == "__main__":
    main()
