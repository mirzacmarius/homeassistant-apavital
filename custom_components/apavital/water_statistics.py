"""Import Apavital hourly consumption into Home Assistant long-term statistics.

Readings reach the Apavital portal hours after they happen, and Home Assistant
may be offline for a while. Recording usage through a sensor would attribute
all of it to the moment Home Assistant saw it. Importing an external statistic
places every hour of usage at the hour it really happened, which is what the
Energy dashboard needs.

The statistic is kept in litres because the Energy dashboard shows water in
the unit of its source, and household usage reads better as 28 L than as
0.028 m³.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_change_statistics_unit,
    get_last_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .history import hourly_usage, statistics_rows

_LOGGER = logging.getLogger(__name__)

# How far back hours are re-checked against the portal. Estimated readings
# that fill a data gap are replaced by real ones a few hours to days later.
REVISION_WINDOW = timedelta(days=7)

STATISTIC_UNIT = UnitOfVolume.LITERS
LITRES_PER_M3 = 1000

try:  # Home Assistant 2025.4+
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:  # pragma: no cover - older cores
    StatisticMeanType = None


def statistic_id_for(client_code: str) -> str:
    """Return the external statistic id for a client code."""
    return f"{DOMAIN}:{client_code.lower()}_water_consumption"


def _metadata(client_code: str) -> StatisticMetaData:
    metadata: dict = {
        "has_sum": True,
        "name": f"Apavital {client_code} water consumption",
        "source": DOMAIN,
        "statistic_id": statistic_id_for(client_code),
        "unit_of_measurement": STATISTIC_UNIT,
    }
    if StatisticMeanType is not None:
        metadata["mean_type"] = StatisticMeanType.NONE
    else:
        metadata["has_mean"] = False
    if "unit_class" in getattr(StatisticMetaData, "__annotations__", {}):
        metadata["unit_class"] = "volume"
    return StatisticMetaData(**metadata)


async def async_import_statistics(
    hass: HomeAssistant, client_code: str, readings: list[dict]
) -> int:
    """Append new hourly usage and rewrite recent hours the portal revised.

    Returns the number of rows written.
    """
    usage = [
        replace(
            hour,
            consumption=round(hour.consumption * LITRES_PER_M3, 3),
            index=round(hour.index * LITRES_PER_M3, 3),
        )
        for hour in hourly_usage(readings)
    ]
    if not usage:
        return 0

    statistic_id = statistic_id_for(client_code)
    recorder = get_instance(hass)
    metadata = await recorder.async_add_executor_job(
        lambda: get_metadata(hass, statistic_ids={statistic_id})
    )
    stored_unit = (
        metadata[statistic_id][1]["unit_of_measurement"] if statistic_id in metadata else None
    )
    if stored_unit is not None and stored_unit != STATISTIC_UNIT:
        # Versions before 1.4.0 stored m³. Convert the history first; the
        # conversion is queued in the recorder, so import on the next update.
        _LOGGER.info("Converting %s from %s to %s", statistic_id, stored_unit, STATISTIC_UNIT)
        await async_change_statistics_unit(
            hass,
            statistic_id,
            new_unit_of_measurement=STATISTIC_UNIT,
            old_unit_of_measurement=stored_unit,
        )
        return 0
    last = await recorder.async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    revise_from = (usage[-1].start - REVISION_WINDOW).timestamp()
    last_start: float | None = None
    stored: dict[float, float] = {}
    if last.get(statistic_id):
        last_row = last[statistic_id][0]
        last_start = last_row["start"]
        stored[last_start] = float(last_row.get("sum") or 0.0)
        # Include the day before the revised range to anchor the running sum.
        query_start = datetime.fromtimestamp(
            min(revise_from, last_start), timezone.utc
        ) - timedelta(days=1)
        existing = await recorder.async_add_executor_job(
            statistics_during_period,
            hass,
            query_start,
            None,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        for row in existing.get(statistic_id, []):
            if row.get("sum") is not None:
                stored[row["start"]] = float(row["sum"])

    rows = [
        StatisticData(start=dt_util.as_utc(hour.start), state=hour.index, sum=total)
        for hour, total in statistics_rows(usage, stored, last_start, revise_from)
    ]
    if rows:
        _LOGGER.debug("Writing %s hourly rows to %s", len(rows), statistic_id)
        async_add_external_statistics(hass, _metadata(client_code), rows)
    return len(rows)
