"""Data coordinator for Apavital integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    API_URL,
    CONF_CLIENT_CODE,
    CONF_JWT_TOKEN,
    CONF_LEAK_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_LEAK_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ApavitalDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Apavital data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.client_code = entry.data[CONF_CLIENT_CODE]
        self.jwt_token = entry.data[CONF_JWT_TOKEN]
        
        # Get options with defaults
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.leak_threshold = entry.options.get(CONF_LEAK_THRESHOLD, DEFAULT_LEAK_THRESHOLD)
        
        # Diagnostics data
        self.api_calls_count = 0
        self.last_successful_update: datetime | None = None
        self.last_error: str | None = None
        self.consecutive_errors = 0
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Apavital API."""
        self.api_calls_count += 1
        
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
                        self.last_error = "JWT token expired"
                        raise ConfigEntryAuthFailed("JWT token expired. Please reconfigure the integration.")
                    
                    response.raise_for_status()
                    result = await response.json()
                    
                    # Reset error tracking on success
                    self.last_successful_update = datetime.now()
                    self.consecutive_errors = 0
                    self.last_error = None
                    
                    if not result.get("data"):
                        return self._empty_data(result)
                    
                    readings = result["data"]
                    return self._process_readings(readings, result)
                    
        except ConfigEntryAuthFailed:
            raise
        except aiohttp.ClientError as err:
            self.consecutive_errors += 1
            self.last_error = str(err)
            raise UpdateFailed(f"Error communicating with Apavital API: {err}") from err
        except Exception as err:
            self.consecutive_errors += 1
            self.last_error = str(err)
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def _empty_data(self, result: dict) -> dict[str, Any]:
        """Return empty data structure."""
        return {
            "index": 0,
            "consumption_daily": 0,
            "consumption_hourly": 0,
            "consumption_weekly": 0,
            "consumption_monthly": 0,
            "time": "",
            "meter_serial": "",
            "average": result.get("avg", 0),
            "median": result.get("mid", 0),
            "total_readings": 0,
            "leak_detected": False,
            "readings": [],
        }

    def _process_readings(self, readings: list, result: dict) -> dict[str, Any]:
        """Process readings and calculate consumption metrics."""
        last_reading = readings[-1]
        current_index = float(last_reading["INDEX_CIT"])
        
        # Calculate various consumption periods
        hourly_consumption = 0
        daily_consumption = 0
        weekly_consumption = 0
        monthly_consumption = 0
        
        # Hourly (last reading vs previous)
        if len(readings) >= 2:
            prev_index = float(readings[-2]["INDEX_CIT"])
            hourly_consumption = round(current_index - prev_index, 4)
        
        # Daily (last 24 readings)
        if len(readings) >= 24:
            start_index = float(readings[-24]["INDEX_CIT"])
            daily_consumption = round(current_index - start_index, 3)
        
        # Weekly (last 168 readings = 7 days * 24 hours)
        if len(readings) >= 168:
            start_index = float(readings[-168]["INDEX_CIT"])
            weekly_consumption = round(current_index - start_index, 3)
        
        # Monthly estimate (last 720 readings = 30 days * 24 hours)
        if len(readings) >= 720:
            start_index = float(readings[-720]["INDEX_CIT"])
            monthly_consumption = round(current_index - start_index, 3)
        elif len(readings) >= 24:
            # Estimate monthly based on daily average
            monthly_consumption = round(daily_consumption * 30, 3)
        
        # Leak detection: if hourly consumption exceeds threshold
        leak_detected = hourly_consumption > self.leak_threshold
        
        if leak_detected:
            _LOGGER.warning(
                "Potential water leak detected! Consumption: %.4f m³/h (threshold: %.4f m³/h)",
                hourly_consumption,
                self.leak_threshold,
            )
        
        return {
            "index": current_index,
            "consumption_hourly": hourly_consumption,
            "consumption_daily": daily_consumption,
            "consumption_weekly": weekly_consumption,
            "consumption_monthly": monthly_consumption,
            "time": last_reading.get("TIME", ""),
            "meter_serial": last_reading.get("METERSERIAL", ""),
            "average": result.get("avg", 0),
            "median": result.get("mid", 0),
            "total_readings": len(readings),
            "leak_detected": leak_detected,
            "readings": readings[-24:],  # Keep last 24 for charts
        }

    @property
    def diagnostics_data(self) -> dict[str, Any]:
        """Return diagnostics data."""
        return {
            "client_code": self.client_code[:4] + "****",  # Masked
            "api_calls_count": self.api_calls_count,
            "last_successful_update": self.last_successful_update.isoformat() if self.last_successful_update else None,
            "consecutive_errors": self.consecutive_errors,
            "last_error": self.last_error,
            "update_interval_minutes": self.update_interval.total_seconds() / 60 if self.update_interval else None,
            "leak_threshold": self.leak_threshold,
        }
