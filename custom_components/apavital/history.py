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
