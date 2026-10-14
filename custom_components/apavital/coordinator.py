"""Data coordinator for Apavital integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .billing import (
    as_list,
    estimate_next_invoice,
    parse_invoices,
    parse_official_readings,
)
from .const import (
    API_BASE,
    API_URL,
    CONF_CLIENT_CODE,
    CONF_JWT_TOKEN,
    CONF_LEAK_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_LEAK_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .history import APAVITAL_TIMEZONE, parse_reading_time
from .leak import LeakConfirmation, analyze_leak_pattern
from .water_statistics import async_import_statistics, statistic_id_for

_LOGGER = logging.getLogger(__name__)

# Invoices and official readings change about once a month.
BILLING_REFRESH = timedelta(hours=6)


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
        self.statistic_id = statistic_id_for(self.client_code)
        self.statistics_rows_imported = 0
        self.last_statistics_error: str | None = None
        self.leak_confirmation = LeakConfirmation()
        self.billing_rows: dict[str, list[dict]] = {}
        self.billing_fetched_at: datetime | None = None
        self.last_billing_error: str | None = None
        
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
            session = async_get_clientsession(self.hass)
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            data = aiohttp.FormData()
            data.add_field("clientCode", self.client_code)
            data.add_field("ctrAdmin", "false")
            data.add_field("ctrEmail", "")

            async with session.post(
                API_URL,
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 401:
                    self.last_error = "JWT token expired"
                    raise ConfigEntryAuthFailed("JWT token expired. Please reconfigure the integration.")

                response.raise_for_status()
                result = await response.json()

            # Reset error tracking on success
            self.last_successful_update = datetime.now(APAVITAL_TIMEZONE)
            self.consecutive_errors = 0
            self.last_error = None

            if not result.get("data"):
                return self._empty_data(result)

            readings = result["data"]
            await self._async_update_billing(session)
            processed = self._process_readings(readings, result)
            await self._async_update_statistics(readings)
            return processed

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

    async def _async_api(
        self, session: aiohttp.ClientSession, path: str, page: str, label: str, payload: dict | None = None
    ) -> Any:
        """Call a My Apavital endpoint the way the web portal does."""
        context = {"ctrAdmin": False, "ctrEmail": "", "pageName": page, "pageLabel": label}
        headers = {"Authorization": f"Bearer {self.jwt_token}", "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=60)
        if payload is None:
            params = {**context, "ctrAdmin": "false"}
            request = session.get(f"{API_BASE}/{path}", headers=headers, params=params, timeout=timeout)
        else:
            request = session.post(
                f"{API_BASE}/{path}", headers=headers, json={**payload, **context}, timeout=timeout
            )
        async with request as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def _async_update_billing(self, session: aiohttp.ClientSession) -> None:
        """Fetch invoices and official readings; never fails the update."""
        now = datetime.now(APAVITAL_TIMEZONE)
        if self.billing_fetched_at and now - self.billing_fetched_at < BILLING_REFRESH:
            return
        try:
            contracts = as_list(await self._async_api(session, "asocieri", "/evidenta_facturi", "Facturi"))
            contract = next(
                (c for c in contracts if str(c.get("COD_CLIENT")) == str(self.client_code)),
                contracts[0] if contracts else None,
            )
            invoices: list[dict] = []
            if contract is not None:
                invoices = as_list(
                    await self._async_api(
                        session,
                        "facturi",
                        "/evidenta_facturi",
                        "Facturi",
                        {"contract": contract.get("COD_CLIENT"), "loc_con_id": contract.get("ID")},
                    )
                )
            official = as_list(
                await self._async_api(session, "index_history_last_year", "/istoric_citiri", "Istoric Citiri")
            )
        except Exception as err:  # noqa: BLE001 - billing is optional
            self.last_billing_error = str(err)
            _LOGGER.debug("Apavital invoices unavailable: %s", err)
            return
        self.billing_rows = {"invoices": invoices, "official_readings": official}
        self.billing_fetched_at = now
        self.last_billing_error = None

    def _billing_summary(self, current_index: float) -> dict[str, Any]:
        """Last invoice and the estimate of the next one."""
        invoices = parse_invoices(self.billing_rows.get("invoices", []))
        readings = parse_official_readings(self.billing_rows.get("official_readings", []))
        last = invoices[-1] if invoices else None
        estimate = estimate_next_invoice(invoices, readings, current_index)
        return {
            "last_invoice": {
                "amount": last.amount,
                "number": last.number,
                "issued": last.issued.isoformat(),
                "due": last.due.isoformat() if last.due else None,
            } if last else None,
            "estimate": {
                "amount": estimate.amount,
                "price_per_m3": estimate.price_per_m3,
                "consumption_m3": estimate.consumption_m3,
                "since": estimate.since.isoformat(),
                "invoices_used": estimate.invoices_used,
            } if estimate else None,
        }

    async def _async_update_statistics(self, readings: list) -> None:
        """Import hourly usage into long-term statistics without failing the update."""
        try:
            added = await async_import_statistics(self.hass, self.client_code, readings)
        except Exception as err:  # noqa: BLE001 - statistics must never break the sensors
            self.last_statistics_error = str(err)
            _LOGGER.warning("Could not import Apavital statistics: %s", err)
            return
        self.last_statistics_error = None
        self.statistics_rows_imported += added
        if added:
            _LOGGER.debug("Imported %s hourly water statistics rows", added)

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

    def _parse_reading_time(self, time_str: str) -> datetime | None:
        """Parse reading timestamp string to a timezone-aware datetime."""
        return parse_reading_time(time_str)

    def _find_reading_at_or_before(self, readings: list, target_time: datetime) -> dict | None:
        """Find the reading closest to but not after target_time."""
        for reading in reversed(readings):
            reading_time = self._parse_reading_time(reading.get("TIME", ""))
            if reading_time and reading_time <= target_time:
                return reading
        return None

    def _calculate_hourly_consumptions(self, readings: list) -> list[tuple[datetime | None, float]]:
        """Calculate consumption for each interval between consecutive readings.
        
        Returns list of (timestamp, consumption) tuples.
        """
        consumptions = []
        for i in range(1, len(readings)):
            prev_reading = readings[i - 1]
            curr_reading = readings[i]
            
            prev_index = float(prev_reading.get("INDEX_CIT", 0))
            curr_index = float(curr_reading.get("INDEX_CIT", 0))
            curr_time = self._parse_reading_time(curr_reading.get("TIME", ""))
            
            consumption = round(curr_index - prev_index, 4)
            consumptions.append((curr_time, consumption))
        
        return consumptions

    def _process_readings(self, readings: list, result: dict) -> dict[str, Any]:
        """Process readings and calculate consumption metrics."""
        last_reading = readings[-1]
        current_index = float(last_reading["INDEX_CIT"])
        now = datetime.now(APAVITAL_TIMEZONE)
        
        # Calculate various consumption periods
        hourly_consumption = 0
        daily_consumption = 0
        weekly_consumption = 0
        monthly_consumption = 0
        
        # Hourly (last reading vs previous)
        hour_start = None
        if len(readings) >= 2:
            hour_start = self._parse_reading_time(readings[-2].get("TIME", ""))
            prev_index = float(readings[-2]["INDEX_CIT"])
            hourly_consumption = round(current_index - prev_index, 4)
        
        # Current day consumption (since midnight today)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_reading = self._find_reading_at_or_before(readings, today_midnight)
        if day_start_reading:
            start_index = float(day_start_reading["INDEX_CIT"])
            daily_consumption = round(current_index - start_index, 3)
        
        # Current week consumption (since Monday midnight)
        days_since_monday = now.weekday()  # Monday = 0
        week_start = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        week_start_reading = self._find_reading_at_or_before(readings, week_start)
        if week_start_reading:
            start_index = float(week_start_reading["INDEX_CIT"])
            weekly_consumption = round(current_index - start_index, 3)
        
        # Current month consumption (since 1st of month midnight)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_reading = self._find_reading_at_or_before(readings, month_start)
        if month_start_reading:
            start_index = float(month_start_reading["INDEX_CIT"])
            monthly_consumption = round(current_index - start_index, 3)
        
        # Advanced leak detection using pattern analysis
        leak_analysis = self.leak_confirmation.apply(
            analyze_leak_pattern(
                self._calculate_hourly_consumptions(readings),
                [float(r.get("INDEX_CIT", 0)) for r in readings],
                self.leak_threshold,
            ),
            self._parse_reading_time(last_reading.get("TIME", "")),
        )
        
        if leak_analysis.is_leak:
            _LOGGER.warning(
                "Potential water leak detected! Confidence: %.0f%% - %s",
                leak_analysis.confidence * 100,
                leak_analysis.reason,
            )
        
        return {
            "index": current_index,
            "consumption_hourly": hourly_consumption,
            "consumption_daily": daily_consumption,
            "consumption_weekly": weekly_consumption,
            "consumption_monthly": monthly_consumption,
            "time": last_reading.get("TIME", ""),
            "last_reading_time": self._parse_reading_time(last_reading.get("TIME", "")),
            "hour_start": hour_start,
            "day_start": today_midnight,
            "week_start": week_start,
            "month_start": month_start,
            "meter_serial": last_reading.get("METERSERIAL", ""),
            "average": result.get("avg", 0),
            "median": result.get("mid", 0),
            "total_readings": len(readings),
            # Leak detection data
            "leak_detected": leak_analysis.is_leak,
            "leak_confidence": leak_analysis.confidence,
            "leak_reason": leak_analysis.reason,
            "leak_consecutive_hours": leak_analysis.consecutive_hours,
            "leak_cv": leak_analysis.coefficient_of_variation,
            "leak_r_squared": leak_analysis.r_squared,
            "leak_night_consumption": leak_analysis.night_consumption,
            "leak_avg_flow": leak_analysis.avg_hourly_flow,
            "leak_factors": leak_analysis.factors,
            "leak_awaiting_confirmation": leak_analysis.awaiting_confirmation,
            "billing": self._billing_summary(current_index),
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
            "statistic_id": self.statistic_id,
            "statistics_rows_imported": self.statistics_rows_imported,
            "last_statistics_error": self.last_statistics_error,
            "billing_fetched_at": self.billing_fetched_at.isoformat() if self.billing_fetched_at else None,
            "last_billing_error": self.last_billing_error,
        }
