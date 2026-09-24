"""Учебное время с вычитанием перекрывающихся пауз занятия и АРМ."""

from datetime import UTC, datetime


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def active_seconds(start: datetime, end: datetime, *pause_lists: list) -> float:
    start, end = aware(start), aware(end)
    intervals = []
    for pauses in pause_lists:
        for pause in pauses or []:
            left = max(start, aware(pause.started_at))
            right = min(end, aware(pause.finished_at) if pause.finished_at else end)
            if right > left:
                intervals.append((left, right))
    intervals.sort()
    excluded = 0.0
    latest = start
    for left, right in intervals:
        if right <= latest:
            continue
        excluded += max(0, (right - max(left, latest)).total_seconds())
        latest = right
    return max(0.0, (end - start).total_seconds() - excluded)
