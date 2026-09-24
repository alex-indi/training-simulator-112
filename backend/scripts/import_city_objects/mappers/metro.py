"""Dataset 624: входы агрегируются по NameOfStation в станции Москвы."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from .education import clean

SOURCE = "data.mos.ru:624"


def _coordinate(value: object, minimum: int, maximum: int) -> Decimal | None:
    try:
        result = Decimal(clean(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() and minimum <= result <= maximum else None


def map_metro(rows: list[dict]) -> tuple[list[dict], dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    missing_name = 0
    outside_entrances = 0
    for row in rows:
        cells = row["Cells"]
        name = clean(cells.get("NameOfStation"))
        if not name:
            missing_name += 1
            continue
        if clean(cells.get("OnTerritoryOfMoscow")).lower() != "да":
            outside_entrances += 1
            continue
        groups[name].append(row)

    objects = []
    missing_coordinates = 0
    conflicting_districts = 0
    for name, entrances in sorted(groups.items()):
        cells_list = [row["Cells"] for row in entrances]
        coordinates = [
            (
                _coordinate(c.get("Latitude_WGS84"), -90, 90),
                _coordinate(c.get("Longitude_WGS84"), -180, 180),
            )
            for c in cells_list
        ]
        valid = [(lat, lon) for lat, lon in coordinates if lat is not None and lon is not None]
        missing_coordinates += len(entrances) - len(valid)
        districts = sorted({clean(c.get("District")) for c in cells_list} - {""})
        areas = sorted({clean(c.get("AdmArea")) for c in cells_list} - {""})
        conflicting_districts += len(districts) > 1
        entrance_ids = sorted(
            str(row.get("global_id") or row["Cells"].get("global_id")) for row in entrances
        )
        if "None" in entrance_ids:
            raise ValueError(f"Dataset 624: вход станции {name} без global_id")
        objects.append(
            {
                "source": SOURCE,
                "source_dataset_id": "624",
                "external_id": f"station:{name}",
                "name": name,
                "object_type_code": "METRO_STATION",
                "address": None,
                "district": districts[0] if len(districts) == 1 else None,
                "administrative_area": areas[0] if len(areas) == 1 else None,
                "latitude": str(sum(lat for lat, _ in valid) / len(valid)) if valid else None,
                "longitude": str(sum(lon for _, lon in valid) / len(valid)) if valid else None,
                "attributes": {
                    "station_name": name,
                    "has_underground_area": any(
                        "подземн" in clean(c.get("VestibuleType")).lower() for c in cells_list
                    ),
                    "entrance_count": len(entrances),
                    "source_entrance_ids": entrance_ids,
                    "lines": sorted({clean(c.get("Line")) for c in cells_list} - {""}),
                    "districts": districts,
                    "administrative_areas": areas,
                },
                "tags": ["transport", "underground", "mass_people"],
            }
        )
    return objects, {
        "missing_name": missing_name,
        "outside_moscow_entrances": outside_entrances,
        "missing_entrance_coordinates": missing_coordinates,
        "stations_with_multiple_districts": conflicting_districts,
        "station_count": len(objects),
    }
