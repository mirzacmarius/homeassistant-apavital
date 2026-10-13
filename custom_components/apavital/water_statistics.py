"""Import Apavital hourly consumption into Home Assistant long-term statistics.

Readings reach the Apavital portal hours after they happen, and Home Assistant
may be offline for a while. Recording usage through a sensor would attribute
all of it to the moment Home Assistant saw it. Importing an external statistic
places every hour of usage at the hour it really happened, which is what the
Energy dashboard needs.
"""
from __future__ import annotations

import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .history import hourly_usage

_LOGGER = logging.getLogger(__name__)

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
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
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
    """Append hourly usage newer than the last imported hour. Returns rows added."""
    usage = hourly_usage(readings)
    if not usage:
        return 0

    statistic_id = statistic_id_for(client_code)
    last = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    last_start: float | None = None
    running_sum = 0.0
    if last.get(statistic_id):
        last_start = last[statistic_id][0]["start"]
        running_sum = float(last[statistic_id][0].get("sum") or 0.0)

    rows: list[StatisticData] = []
    for hour in usage:
        if last_start is not None and hour.start.timestamp() <= last_start:
            continue
        running_sum = round(running_sum + hour.consumption, 4)
        rows.append(
            StatisticData(
                start=dt_util.as_utc(hour.start), state=hour.index, sum=running_sum
            )
        )

    if rows:
        _LOGGER.debug("Adding %s hourly rows to %s", len(rows), statistic_id)
        async_add_external_statistics(hass, _metadata(client_code), rows)
    return len(rows)
