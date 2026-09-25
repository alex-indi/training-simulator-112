# Ручная выгрузка наборов data.mos.ru для UT112-24.4

Команды выполнять в терминале из каталога `backend/`. Ключ берётся из `MOS_API_KEY` в корневом `.env` проекта или из переменной окружения. Не вставляйте ключ в команду: API-клиент сам добавит его к запросу и не выведет на экран.

## 1. Проверить соединение

```bash
cd backend
uv run python -m scripts.import_city_objects.mos_api_client check 747 --connect-timeout 10 --read-timeout 60
```

`747` — уже известный набор образовательных учреждений. При успешном ответе команда выведет `Набор 747 доступен`. Если соединение снова завершится ошибкой, пришлите текст ошибки без содержимого `.env`.

## 2. Выгрузить медицинские наборы

Запустите команды из `backend/`, чтобы сохранить паспорта и строки:

```bash
uv run python -m scripts.import_city_objects.mos_api_client fetch 502 hospitals_children
uv run python -m scripts.import_city_objects.mos_api_client fetch 517 hospitals_adults
uv run python -m scripts.import_city_objects.mos_api_client fetch 503 polyclinics_adults
uv run python -m scripts.import_city_objects.mos_api_client fetch 505 polyclinics_children
uv run python -m scripts.import_city_objects.mos_api_client fetch 516 emergency_stations
```

Если нужно проверить название набора по ID, найдите его на [официальном портале data.mos.ru](https://data.mos.ru/). ID находится в адресе страницы после `/opendata/`. Имя файла допускает только строчные латинские буквы, цифры и `_`.

Каждая команда создаёт три файла в `backend/seed/object_registry/source_data/`: `<имя>_dataset_info.json`, `<имя>_raw_rows.json` и `<имя>_fetch_report.json`. В отчёте находятся ID и количество строк. Уже существующие файлы защищены от случайной перезаписи; для обновления добавьте `--force`.

После выгрузки сообщите имена наборов и их ID. На основе этих файлов можно проверить реальные поля, добавить медицинские mapper-ы и загрузить объекты в `city_objects`. Текущая команда `import_objects build` пока обрабатывает только образовательные учреждения и метро.
