"""Tests for leak detection (no Home Assistant needed).

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import unittest

_PATH = Path(__file__).parents[1] / "custom_components" / "apavital" / "leak.py"
_SPEC = importlib.util.spec_from_file_location("apavital_leak", _PATH)
leak = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = leak
_SPEC.loader.exec_module(leak)

TZ = ZoneInfo("Europe/Bucharest")


def series(start: datetime, litres: list[float]) -> tuple[list, list[float]]:
    """Hourly (time, m³) pairs and the meter index they produce."""
    hourly, index = [], [65.0]
    for hour, value in enumerate(litres, start=1):
        hourly.append((start + timedelta(hours=hour), value / 1000))
        index.append(index[-1] + value / 1000)
    return hourly, index


class AnalyzeLeakPatternTest(unittest.TestCase):
    def test_constant_night_flow_is_suspected(self) -> None:
        # Estimated readings Apavital served on 14.10.2026 for a 12h gap.
        hourly, index = series(datetime(2026, 10, 13, 0, tzinfo=TZ), [7] * 11 + [8])
        result = leak.analyze_leak_pattern(hourly, index, 0.01)
        self.assertTrue(result.is_leak)
        self.assertTrue(result.night_consumption)

    def test_normal_daytime_usage_is_not_a_leak(self) -> None:
        # Real readings for 13.10.2026 07:00-19:00, including the 10 L/h threshold.
        hourly, index = series(
            datetime(2026, 10, 13, 6, tzinfo=TZ), [10, 6, 8, 10, 6, 27, 9, 13, 6, 25, 24, 22]
        )
        result = leak.analyze_leak_pattern(hourly, index, 0.01)
        self.assertFalse(result.is_leak)
        self.assertNotIn("r_squared", result.factors)
        self.assertGreater(result.r_squared, 0.95)

    def test_idle_meter_is_not_a_leak(self) -> None:
        hourly, index = series(datetime(2026, 10, 12, 20, tzinfo=TZ), [0] * 12)
        result = leak.analyze_leak_pattern(hourly, index, 0.01)
        self.assertFalse(result.is_leak)
        self.assertEqual(result.reason, "No leak indicators")

    def test_insufficient_data(self) -> None:
        hourly, index = series(datetime(2026, 10, 13, 0, tzinfo=TZ), [7, 7])
        result = leak.analyze_leak_pattern(hourly, index, 0.01)
        self.assertFalse(result.is_leak)
        self.assertEqual(result.reason, "Insufficient data for analysis")


class LeakConfirmationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.confirmation = leak.LeakConfirmation()
        self.t0 = datetime(2026, 10, 13, 13, tzinfo=TZ)

    def suspected(self, **overrides):
        values = dict(
            is_leak=True, confidence=0.98, reason="12h continuous consumption",
            consecutive_hours=12, coefficient_of_variation=0.04, r_squared=1.0,
            night_consumption=True, avg_hourly_flow=0.007, factors={},
        )
        values.update(overrides)
        return leak.LeakAnalysisResult(**values)

    def test_first_suspicion_waits_for_next_reading(self) -> None:
        result = self.confirmation.apply(self.suspected(), self.t0)
        self.assertFalse(result.is_leak)
        self.assertTrue(result.awaiting_confirmation)
        self.assertIn("awaiting confirmation", result.reason)

    def test_same_reading_polled_again_is_not_confirmation(self) -> None:
        self.confirmation.apply(self.suspected(), self.t0)
        self.assertFalse(self.confirmation.apply(self.suspected(), self.t0).is_leak)

    def test_persisting_leak_is_confirmed_by_newer_reading(self) -> None:
        self.confirmation.apply(self.suspected(), self.t0)
        result = self.confirmation.apply(self.suspected(), self.t0 + timedelta(hours=1))
        self.assertTrue(result.is_leak)
        self.assertFalse(result.awaiting_confirmation)

    def test_revised_data_clears_suspicion(self) -> None:
        # 14.10.2026: estimated data scored 98%, the next batch only 11%, then 65%.
        self.confirmation.apply(self.suspected(), self.t0)
        self.confirmation.apply(self.suspected(is_leak=False), self.t0 + timedelta(hours=2))
        result = self.confirmation.apply(self.suspected(), self.t0 + timedelta(hours=6))
        self.assertFalse(result.is_leak)


if __name__ == "__main__":
    unittest.main()
