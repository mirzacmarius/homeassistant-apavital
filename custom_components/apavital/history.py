"""Pure helpers that turn Apavital meter readings into hourly usage.

Kept free of Home Assistant imports so the logic can be unit tested on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

# Apavital meters are read in Romanian local time.
APAVITAL_TIMEZONE = ZoneInfo("Europe/Bucharest")

_TIME_FORMATS = ("%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


@dataclass(frozen=True)
class HourlyUsage:
    """Water used during one clock hour."""

    start: datetime  # timezone-aware, top of the hour
    consumption: float  # m³ used during the hour
    index: float  # meter index at the end of the hour


def parse_reading_time(value: str, tz: tzinfo = APAVITAL_TIMEZONE) -> datetime | None:
    """Parse an Apavital timestamp into a timezone-aware datetime."""
    if not value:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    return None


def parse_number(value: object) -> float | None:
    """Parse a numeric field that may use a decimal comma."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def hourly_usage(readings: list[dict], tz: tzinfo = APAVITAL_TIMEZONE) -> list[HourlyUsage]:
    """Aggregate consecutive meter readings into per-hour consumption.

    A reading taken at T closes the interval that started at the previous
    reading, so its consumption is attributed to the hour ending at T. When
    the index goes backwards (meter replaced) the reading's own CONSUM field is
    used instead of the index difference.
    """
    parsed: list[tuple[datetime, float, float | None, str]] = []
    for reading in readings:
        time = parse_reading_time(reading.get("TIME", ""), tz)
        index = parse_number(reading.get("INDEX_CIT"))
        if time is None or index is None:
            continue
        parsed.append(
            (time, index, parse_number(reading.get("CONSUM")), reading.get("METERSERIAL", ""))
        )
    parsed.sort(key=lambda item: item[0].timestamp())

    hours: dict[datetime, HourlyUsage] = {}
    for (_, prev_index, _, prev_serial), (time, index, consum, serial) in zip(parsed, parsed[1:]):
        delta = index - prev_index
        if delta < 0 or (prev_serial and serial and prev_serial != serial):
            delta = consum if consum is not None and consum >= 0 else 0.0
        end = time.astimezone(ZoneInfo("UTC")).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=1) if time.minute == 0 and time.second == 0 else end
        previous = hours.get(start)
        hours[start] = HourlyUsage(
            start=start,
            consumption=round((previous.consumption if previous else 0.0) + delta, 4),
            index=index,
        )
    return [hours[key] for key in sorted(hours)]


def statistics_rows(
    usage: list[HourlyUsage],
    stored: dict[float, float],
    last_start: float | None,
    revise_from: float,
) -> list[tuple[HourlyUsage, float]]:
    """Plan the (hour, running sum) statistics rows to write.

    Hours newer than the last stored hour (`last_start`) are appended. Stored
    hours starting at or after `revise_from` are rewritten when the portal has
    since changed them, which happens when estimated readings that filled a
    data gap are replaced by real ones.

    `stored` maps the start timestamp of already stored hours to their sum. It
    must include the stored hour right before the revised range so the running
    sum can continue from it; without it only new hours are appended.
    """
    if not usage:
        return []
    if last_start is None:
        rows, running = [], 0.0
        for hour in usage:
            running = round(running + hour.consumption, 4)
            rows.append((hour, running))
        return rows

    starts = [h.start.timestamp() for h in usage]
    window_start = min((s for s in starts if s > last_start or s >= revise_from), default=None)
    if window_start is None:
        return []
    anchors = [start for start in stored if start < window_start]
    if not anchors:
        window_start = min((s for s in starts if s > last_start), default=None)
        anchors = [last_start] if last_start in stored else []
        if window_start is None or not anchors:
            return []
    running = stored[max(anchors)]

    # Stored hours the portal no longer reports used no water; rewrite them too
    # so the running sum stays consistent.
    by_start = {h.start.timestamp(): h for h in usage if h.start.timestamp() >= window_start}
    starts = sorted(set(by_start) | {s for s in stored if window_start <= s <= starts[-1]})

    first = by_start[min(by_start)]
    index = round(first.index - first.consumption, 4)
    rows: list[tuple[HourlyUsage, float]] = []
    changed = False
    for start in starts:
        hour = by_start.get(start)
        if hour is None:
            hour = HourlyUsage(
                start=datetime.fromtimestamp(start, ZoneInfo("UTC")),
                consumption=0.0,
                index=index,
            )
        index = hour.index
        running = round(running + hour.consumption, 4)
        if not changed and start in stored and abs(stored[start] - running) < 1e-6:
            continue
        changed = True
        rows.append((hour, running))
    return rows
