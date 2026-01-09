"""Data coordinator for Apavital integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_URL, CONF_CLIENT_CODE, CONF_JWT_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=1)


class ApavitalDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Apavital data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.client_code = entry.data[CONF_CLIENT_CODE]
        self.jwt_token = entry.data[CONF_JWT_TOKEN]
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Apavital API."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.jwt_token}"}
                data = aiohttp.FormData()
                data.add_field("clientCode", self.client_code)
                data.add_field("ctrAdmin", "false")
                data.add_field("ctrEmail", "")
                
                async with session.post(
                    API_URL, 
                    headers=headers, 
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 401:
                        raise UpdateFailed("JWT token expired. Please reconfigure the integration.")
                    
                    response.raise_for_status()
                    result = await response.json()
                    
                    if not result.get("data"):
                        return {
                            "index": 0,
                            "consumption_daily": 0,
                            "time": "",
                            "meter_serial": "",
                            "average": result.get("avg", 0),
                            "median": result.get("mid", 0),
                        }
                    
                    readings = result["data"]
                    last_reading = readings[-1]
                    
                    # Calculate daily consumption (last 24 readings)
                    daily_consumption = 0
                    if len(readings) >= 24:
                        start_index = float(readings[-24]["INDEX_CIT"])
                        end_index = float(last_reading["INDEX_CIT"])
                        daily_consumption = round(end_index - start_index, 3)
                    
                    return {
                        "index": float(last_reading["INDEX_CIT"]),
                        "consumption_daily": daily_consumption,
                        "time": last_reading.get("TIME", ""),
                        "meter_serial": last_reading.get("METERSERIAL", ""),
                        "average": result.get("avg", 0),
                        "median": result.get("mid", 0),
                        "total_readings": len(readings),
                    }
                    
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with Apavital API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err
