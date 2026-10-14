"""Leak detection from Apavital hourly consumption.

Kept free of Home Assistant imports so the logic can be unit tested on its own.

Apavital meters report with a delay, and after an outage the portal can serve
estimated readings that spread the missing usage evenly over the gap. Evenly
spread usage looks exactly like a leak (constant flow, including at night), so
a suspected leak is only reported once a later reading confirms it.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

LEAK_MIN_HOURS_FOR_ANALYSIS = 4  # Minimum hours of data needed
LEAK_ANALYSIS_WINDOW = 12  # Hours of recent data to analyse
LEAK_CONSECUTIVE_THRESHOLD = 6  # Hours of continuous consumption = suspicious
LEAK_CV_THRESHOLD = 0.5  # Coefficient of variation below this = constant flow
LEAK_R2_THRESHOLD = 0.95  # R² above this = very linear (reported, not scored)
LEAK_MIN_FLOW_THRESHOLD = 0.005  # m³/h (5 L/h) minimum to count as consumption
LEAK_NIGHT_HOURS = (1, 5)  # 1 AM to 5 AM
LEAK_SCORE_THRESHOLD = 50  # Points needed to suspect a leak


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
    awaiting_confirmation: bool = False


def calculate_r_squared(values: list[float]) -> float:
    """Calculate R² (coefficient of determination) for linearity.

    A perfectly linear sequence has R² = 1.0. A meter index never goes down,
    so any steady usage scores close to 1.0; this is why R² is only reported.
    """
    if len(values) < 3:
        return 0.0

    n = len(values)
    x_values = list(range(n))
    x_mean = sum(x_values) / n
    y_mean = sum(values) / n

    ss_tot = sum((y - y_mean) ** 2 for y in values)
    if ss_tot == 0:  # All values are identical
        return 1.0

    ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, values))
    ss_xx = sum((x - x_mean) ** 2 for x in x_values)
    if ss_xx == 0:
        return 0.0

    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_values, values))
    return max(0.0, min(1.0, 1 - (ss_res / ss_tot)))


def count_consecutive_nonzero(
    consumptions: list[float], threshold: float = LEAK_MIN_FLOW_THRESHOLD
) -> int:
    """Count consecutive readings with consumption above threshold (from most recent)."""
    count = 0
    for consumption in reversed(consumptions):
        if consumption > threshold:
            count += 1
        else:
            break
    return count


def has_night_consumption(hourly_data: list[tuple[datetime | None, float]]) -> bool:
    """Check if there's consumption during night hours (1-5 AM)."""
    night_start, night_end = LEAK_NIGHT_HOURS
    for timestamp, consumption in hourly_data:
        if timestamp is None:
            continue
        if night_start <= timestamp.hour < night_end and consumption > LEAK_MIN_FLOW_THRESHOLD:
            return True
    return False


def analyze_leak_pattern(
    hourly_data: list[tuple[datetime | None, float]],
    index_values: list[float],
    leak_threshold: float,
) -> LeakAnalysisResult:
    """Score the recent consumption pattern for signs of a leak.

    Evidence (max 90 points, 50 needed):
    - Consecutive hours with consumption (leaks don't stop): up to 30
    - Low coefficient of variation (leaks have constant flow): up to 25
    - Consumption during the night (1-5 AM): 20
    - Average flow above the configured threshold: 15
    """
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

    window = min(LEAK_ANALYSIS_WINDOW, len(hourly_data))
    recent_data = hourly_data[-window:]
    recent_consumptions = [c for _, c in recent_data]

    consecutive_hours = count_consecutive_nonzero(recent_consumptions)

    positive = [c for c in recent_consumptions if c > LEAK_MIN_FLOW_THRESHOLD]
    cv = None
    if len(positive) >= 3:
        mean_consumption = statistics.mean(positive)
        if mean_consumption > 0:
            cv = statistics.stdev(positive) / mean_consumption

    recent_index = index_values[-(window + 1):]
    r_squared = calculate_r_squared(recent_index) if len(recent_index) >= 3 else None

    night_consumption = has_night_consumption(recent_data)
    avg_flow = statistics.mean(recent_consumptions) if recent_consumptions else 0.0

    leak_score = 0.0
    factors: dict[str, Any] = {}
    reasons: list[str] = []

    if consecutive_hours >= LEAK_CONSECUTIVE_THRESHOLD:
        factor_score = min(30, consecutive_hours * 5)
        leak_score += factor_score
        factors["consecutive_hours"] = {
            "value": consecutive_hours,
            "threshold": LEAK_CONSECUTIVE_THRESHOLD,
            "score": factor_score,
        }
        reasons.append(f"{consecutive_hours}h continuous consumption")

    if cv is not None and cv < LEAK_CV_THRESHOLD:
        factor_score = 25 * (1 - cv / LEAK_CV_THRESHOLD)
        leak_score += factor_score
        factors["coefficient_of_variation"] = {
            "value": round(cv, 3),
            "threshold": LEAK_CV_THRESHOLD,
            "score": round(factor_score, 1),
        }
        reasons.append(f"constant flow rate (CV={cv:.2f})")

    if night_consumption:
        leak_score += 20
        factors["night_consumption"] = {"value": True, "score": 20}
        reasons.append("night-time usage detected")

    if avg_flow > leak_threshold:
        leak_score += 15
        factors["exceeds_threshold"] = {
            "value": round(avg_flow, 4),
            "threshold": leak_threshold,
            "score": 15,
        }
        reasons.append(f"high flow ({avg_flow:.3f} m³/h)")

    return LeakAnalysisResult(
        is_leak=leak_score >= LEAK_SCORE_THRESHOLD,
        confidence=min(1.0, leak_score / 100),
        reason="; ".join(reasons) if reasons else "No leak indicators",
        consecutive_hours=consecutive_hours,
        coefficient_of_variation=round(cv, 3) if cv is not None else None,
        r_squared=round(r_squared, 4) if r_squared is not None else None,
        night_consumption=night_consumption,
        avg_hourly_flow=round(avg_flow, 4),
        factors=factors,
    )


class LeakConfirmation:
    """Report a leak only when it is still suspected after a newer reading.

    Estimated readings are replaced by real ones on a later fetch, so a false
    pattern disappears before it is confirmed, while a real leak persists.
    """

    def __init__(self) -> None:
        self._suspected_since: datetime | None = None

    def update(self, suspected: bool, latest_reading: datetime | None) -> bool:
        """Record the latest analysis and return whether the leak is confirmed."""
        if not suspected or latest_reading is None:
            self._suspected_since = None
            return False
        if self._suspected_since is None or latest_reading < self._suspected_since:
            self._suspected_since = latest_reading
            return False
        return latest_reading > self._suspected_since

    def apply(self, result: LeakAnalysisResult, latest_reading: datetime | None) -> LeakAnalysisResult:
        """Return the result with is_leak gated on confirmation."""
        confirmed = self.update(result.is_leak, latest_reading)
        if result.is_leak and not confirmed:
            result.is_leak = False
            result.awaiting_confirmation = True
            result.reason = f"{result.reason} (awaiting confirmation from next reading)"
        return result
