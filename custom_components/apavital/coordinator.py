"""Data coordinator for Apavital integration."""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
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

# Leak detection constants
LEAK_MIN_HOURS_FOR_ANALYSIS = 4  # Minimum hours of data needed
LEAK_CONSECUTIVE_THRESHOLD = 6  # Hours of continuous consumption = suspicious
LEAK_CV_THRESHOLD = 0.5  # Coefficient of variation below this = constant flow
LEAK_R2_THRESHOLD = 0.95  # R² above this = very linear (leak-like)
LEAK_MIN_FLOW_THRESHOLD = 0.005  # m³/h (5 L/h) minimum to count as consumption
LEAK_NIGHT_HOURS = (1, 5)  # 1 AM to 5 AM


@dataclass
class LeakAnalysisResult:
    """Result of leak detection analysis."""
    
    is_leak: bool
    confidence: float  # 0.0 to 1.0
    reason: str
    consecutive_hours: int
    coefficient_of_variation: float | None
    r_squared: float | None
    night_consumption: bool
    avg_hourly_flow: float
    factors: dict[str, Any]


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

    def _parse_reading_time(self, time_str: str) -> datetime | None:
        """Parse reading timestamp string to datetime."""
        if not time_str:
            return None
        try:
            # Try common formats: "2024-01-15 14:00:00" or "2024-01-15T14:00:00"
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M:%S"):
                try:
                    return datetime.strptime(time_str, fmt)
                except ValueError:
                    continue
            return None
        except Exception:
            return None

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

    def _calculate_r_squared(self, values: list[float]) -> float:
        """Calculate R² (coefficient of determination) for linearity.
        
        A perfectly linear sequence has R² = 1.0.
        This measures how well the meter index follows a straight line.
        """
        if len(values) < 3:
            return 0.0
        
        n = len(values)
        x_values = list(range(n))  # 0, 1, 2, 3, ...
        
        # Calculate means
        x_mean = sum(x_values) / n
        y_mean = sum(values) / n
        
        # Calculate sums for linear regression
        ss_tot = sum((y - y_mean) ** 2 for y in values)
        
        if ss_tot == 0:  # All values are identical
            return 1.0  # Perfect "linearity" (flat line)
        
        # Calculate slope and intercept for best fit line
        ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, values))
        ss_xx = sum((x - x_mean) ** 2 for x in x_values)
        
        if ss_xx == 0:
            return 0.0
        
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        
        # Calculate residual sum of squares
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_values, values))
        
        r_squared = 1 - (ss_res / ss_tot)
        return max(0.0, min(1.0, r_squared))  # Clamp to [0, 1]

    def _count_consecutive_nonzero(self, consumptions: list[float], threshold: float = LEAK_MIN_FLOW_THRESHOLD) -> int:
        """Count consecutive readings with consumption above threshold (from most recent)."""
        count = 0
        for consumption in reversed(consumptions):
            if consumption > threshold:
                count += 1
            else:
                break  # Stop at first zero/low consumption
        return count

    def _has_night_consumption(self, hourly_data: list[tuple[datetime | None, float]]) -> bool:
        """Check if there's consumption during night hours (1-5 AM)."""
        night_start, night_end = LEAK_NIGHT_HOURS
        
        for timestamp, consumption in hourly_data:
            if timestamp is None:
                continue
            hour = timestamp.hour
            if night_start <= hour < night_end and consumption > LEAK_MIN_FLOW_THRESHOLD:
                return True
        return False

    def _analyze_leak_pattern(self, readings: list) -> LeakAnalysisResult:
        """Perform sophisticated leak detection using multiple factors.
        
        This analyzes the consumption pattern to detect leaks by looking for:
        1. Consecutive hours with non-zero consumption (leaks don't stop)
        2. Low coefficient of variation (leaks have constant flow)
        3. High R² score (linear meter increase = constant flow)
        4. Night-time consumption (nobody uses water at 3 AM normally)
        5. Sustained minimum flow over time
        """
        # Calculate hourly consumptions from readings
        hourly_data = self._calculate_hourly_consumptions(readings)
        
        if len(hourly_data) < LEAK_MIN_HOURS_FOR_ANALYSIS:
            return LeakAnalysisResult(
                is_leak=False,
                confidence=0.0,
                reason="Insufficient data for analysis",
                consecutive_hours=0,
                coefficient_of_variation=None,
                r_squared=None,
                night_consumption=False,
                avg_hourly_flow=0.0,
                factors={},
            )
        
        consumptions = [c for _, c in hourly_data]
        
        # Get last N hours for analysis (use up to 12 hours)
        analysis_window = min(12, len(consumptions))
        recent_consumptions = consumptions[-analysis_window:]
        recent_data = hourly_data[-analysis_window:]
        
        # Factor 1: Consecutive non-zero hours
        consecutive_hours = self._count_consecutive_nonzero(recent_consumptions)
        
        # Factor 2: Coefficient of Variation (CV = std/mean)
        # Low CV means consistent flow (leak), high CV means variable usage (normal)
        positive_consumptions = [c for c in recent_consumptions if c > LEAK_MIN_FLOW_THRESHOLD]
        cv = None
        if len(positive_consumptions) >= 3:
            mean_consumption = statistics.mean(positive_consumptions)
            if mean_consumption > 0:
                std_consumption = statistics.stdev(positive_consumptions)
                cv = std_consumption / mean_consumption
        
        # Factor 3: R² score (linearity of index increase)
        # Get the actual index values for the analysis window
        index_values = [float(r.get("INDEX_CIT", 0)) for r in readings[-analysis_window:]]
        r_squared = self._calculate_r_squared(index_values) if len(index_values) >= 3 else None
        
        # Factor 4: Night consumption
        night_consumption = self._has_night_consumption(recent_data)
        
        # Factor 5: Average hourly flow
        avg_flow = statistics.mean(recent_consumptions) if recent_consumptions else 0.0
        
        # Scoring system - accumulate evidence
        leak_score = 0.0
        factors = {}
        
        # Score consecutive hours (max 30 points)
        if consecutive_hours >= LEAK_CONSECUTIVE_THRESHOLD:
            factor_score = min(30, consecutive_hours * 5)
            leak_score += factor_score
            factors["consecutive_hours"] = {
                "value": consecutive_hours,
                "threshold": LEAK_CONSECUTIVE_THRESHOLD,
                "score": factor_score,
            }
        
        # Score low CV (max 25 points) - only if we have enough data
        if cv is not None and cv < LEAK_CV_THRESHOLD:
            # Lower CV = more points (constant flow)
            factor_score = 25 * (1 - cv / LEAK_CV_THRESHOLD)
            leak_score += factor_score
            factors["coefficient_of_variation"] = {
                "value": round(cv, 3),
                "threshold": LEAK_CV_THRESHOLD,
                "score": round(factor_score, 1),
            }
        
        # Score high R² (max 25 points)
        if r_squared is not None and r_squared > LEAK_R2_THRESHOLD:
            factor_score = 25 * ((r_squared - LEAK_R2_THRESHOLD) / (1 - LEAK_R2_THRESHOLD))
            leak_score += factor_score
            factors["r_squared"] = {
                "value": round(r_squared, 4),
                "threshold": LEAK_R2_THRESHOLD,
                "score": round(factor_score, 1),
            }
        
        # Score night consumption (20 points - this is very suspicious)
        if night_consumption:
            leak_score += 20
            factors["night_consumption"] = {
                "value": True,
                "score": 20,
            }
        
        # Bonus: If also exceeds simple threshold, add points
        if avg_flow > self.leak_threshold:
            leak_score += 15
            factors["exceeds_threshold"] = {
                "value": round(avg_flow, 4),
                "threshold": self.leak_threshold,
                "score": 15,
            }
        
        # Normalize to confidence (0-1 scale, cap at 100 points = 1.0)
        confidence = min(1.0, leak_score / 100)
        
        # Determine if leak based on score threshold (50 points = leak)
        is_leak = leak_score >= 50
        
        # Generate human-readable reason
        reasons = []
        if consecutive_hours >= LEAK_CONSECUTIVE_THRESHOLD:
            reasons.append(f"{consecutive_hours}h continuous consumption")
        if cv is not None and cv < LEAK_CV_THRESHOLD:
            reasons.append(f"constant flow rate (CV={cv:.2f})")
        if r_squared is not None and r_squared > LEAK_R2_THRESHOLD:
            reasons.append(f"linear consumption (R²={r_squared:.3f})")
        if night_consumption:
            reasons.append("night-time usage detected")
        if avg_flow > self.leak_threshold:
            reasons.append(f"high flow ({avg_flow:.3f} m³/h)")
        
        reason = "; ".join(reasons) if reasons else "No leak indicators"
        
        return LeakAnalysisResult(
            is_leak=is_leak,
            confidence=confidence,
            reason=reason,
            consecutive_hours=consecutive_hours,
            coefficient_of_variation=round(cv, 3) if cv is not None else None,
            r_squared=round(r_squared, 4) if r_squared is not None else None,
            night_consumption=night_consumption,
            avg_hourly_flow=round(avg_flow, 4),
            factors=factors,
        )

    def _process_readings(self, readings: list, result: dict) -> dict[str, Any]:
        """Process readings and calculate consumption metrics."""
        last_reading = readings[-1]
        current_index = float(last_reading["INDEX_CIT"])
        now = datetime.now()
        
        # Calculate various consumption periods
        hourly_consumption = 0
        daily_consumption = 0
        weekly_consumption = 0
        monthly_consumption = 0
        
        # Hourly (last reading vs previous)
        if len(readings) >= 2:
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
        leak_analysis = self._analyze_leak_pattern(readings)
        
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
