"""Медицинские наборы data.mos.ru: один объект на физический адрес."""

from decimal import Decimal, InvalidOperation

from .education import clean


def _center(cells: dict, address_count: int) -> tuple[str | None, str | None]:
    """Центроид относится к объекту только при единственном адресе."""
    if address_count != 1:
        return None, None
    center = cells.get("geodata_center")
    if not isinstance(center, dict):
        return None, None
    coordinates = center.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None, None
    try:
        longitude, latitude = (Decimal(str(value)) for value in coordinates[:2])
    except InvalidOperation:
        return None, None
    if not (longitude.is_finite() and -180 <= longitude <= 180):
        return None, None
    if not (latitude.is_finite() and -90 <= latitude <= 90):
        return None, None
    return str(latitude), str(longitude)


def _all_day(hours: object) -> bool:
    if not isinstance(hours, list) or len(hours) < 7:
        return False
    return all("круглосуточно" in clean(day.get("WorkHours")).lower() for day in hours)


def map_healthcare(rows: list[dict], dataset_id: int, type_code: str) -> tuple[list[dict], dict]:
    """Сохраняет идентичность строки и каждого адреса в составном external_id."""
    if type_code not in {"HOSPITAL", "POLYCLINIC", "EMERGENCY_STATION"}:
        raise ValueError(f"Неизвестный медицинский тип: {type_code}")

    objects = []
    quality = {
        "source_rows": len(rows),
        "objects": 0,
        "closed_rows": 0,
        "missing_name_rows": 0,
        "missing_address_rows": 0,
        "multiple_address_rows": 0,
        "missing_coordinates": 0,
        "unknown_status_rows": 0,
    }
    for row in rows:
        cells = row["Cells"]
        if clean(cells.get("CloseFlag")).lower() == "закрыто":
            quality["closed_rows"] += 1
            continue
        if not clean(cells.get("CloseFlag")):
            quality["unknown_status_rows"] += 1
        row_id = clean(row.get("global_id") or cells.get("global_id"))
        name = clean(cells.get("ShortName")) or clean(cells.get("FullName"))
        addresses = cells.get("ObjectAddress") or []
        if not row_id:
            raise ValueError(f"Dataset {dataset_id}: строка без global_id")
        if not name:
            quality["missing_name_rows"] += 1
            continue
        if not addresses:
            quality["missing_address_rows"] += 1
            continue
        quality["multiple_address_rows"] += len(addresses) > 1
        latitude, longitude = _center(cells, len(addresses))
        all_day = _all_day(cells.get("WorkingHours"))
        tags = ["medical"]
        if type_code == "HOSPITAL":
            tags.append("patients")
        elif type_code == "POLYCLINIC":
            tags.append("visitors")
        else:
            tags.append("emergency_response")
        if all_day:
            tags.append("24_hours")
        elif type_code == "POLYCLINIC":
            tags.append("daytime")

        for address in addresses:
            address_id = clean(address.get("global_id"))
            if not address_id:
                raise ValueError(f"Dataset {dataset_id}: адрес строки {row_id} без global_id")
            quality["missing_coordinates"] += latitude is None or longitude is None
            objects.append(
                {
                    "source": f"data.mos.ru:{dataset_id}",
                    "source_dataset_id": str(dataset_id),
                    "external_id": f"{row_id}:{address_id}",
                    "name": name,
                    "object_type_code": type_code,
                    "address": clean(address.get("Address")) or None,
                    "district": clean(address.get("District")) or None,
                    "administrative_area": clean(address.get("AdmArea")) or None,
                    "latitude": latitude,
                    "longitude": longitude,
                    "attributes": {
                        "source_row_id": row_id,
                        "source_address_id": address_id,
                        "category": clean(cells.get("Category")),
                        "close_flag": clean(cells.get("CloseFlag")),
                        "full_name": clean(cells.get("FullName")),
                        "working_hours": cells.get("WorkingHours") or [],
                    },
                    "tags": tags,
                }
            )
    quality["objects"] = len(objects)
    return objects, quality
