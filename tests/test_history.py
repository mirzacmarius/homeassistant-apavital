"""Tests for the hourly usage helpers (no Home Assistant needed).

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest

_PATH = Path(__file__).parents[1] / "custom_components" / "apavital" / "history.py"
_SPEC = importlib.util.spec_from_file_location("apavital_history", _PATH)
history = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = history
_SPEC.loader.exec_module(history)


def reading(time: str, index: str, consum: str = "0", serial: str = "M1") -> dict:
    return {"TIME": time, "INDEX_CIT": index, "CONSUM": consum, "METERSERIAL": serial}


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class HourlyUsageTest(unittest.TestCase):
    def test_reading_closes_the_previous_hour(self) -> None:
        usage = history.hourly_usage(
            [
                reading("13.10.2026 00:00:00", "65.500"),
                reading("13.10.2026 01:00:00", "65.520"),
                reading("13.10.2026 02:00:00", "65.520"),
            ]
        )
        # 00:00-01:00 local (EEST, UTC+3) is 21:00-22:00 UTC the day before.
        self.assertEqual([u.start for u in usage], [utc(2026, 10, 12, 21), utc(2026, 10, 12, 22)])
        self.assertEqual([u.consumption for u in usage], [0.02, 0.0])
        self.assertEqual(usage[-1].index, 65.52)

    def test_meter_replacement_uses_consum_instead_of_negative_delta(self) -> None:
        usage = history.hourly_usage(
            [
                reading("01.08.2026 10:00:00", "400.000", serial="OLD"),
                reading("01.08.2026 11:00:00", "0.015", consum="0.015", serial="NEW"),
                reading("01.08.2026 12:00:00", "0.035", serial="NEW"),
            ]
        )
        self.assertEqual([u.consumption for u in usage], [0.015, 0.02])

    def test_decimal_comma_and_unsorted_input(self) -> None:
        usage = history.hourly_usage(
            [
                reading("13.10.2026 02:00:00", "1,250"),
                reading("13.10.2026 01:00:00", "1,200"),
            ]
        )
        self.assertEqual(len(usage), 1)
        self.assertAlmostEqual(usage[0].consumption, 0.05)

    def test_dst_end_keeps_both_hours(self) -> None:
        # On 25.10.2026 clocks go back at 04:00 EEST -> 03:00 EET.
        usage = history.hourly_usage(
            [
                reading("25.10.2026 01:00:00", "10.000"),
                reading("25.10.2026 02:00:00", "10.010"),
                reading("25.10.2026 05:00:00", "10.040"),
            ]
        )
        self.assertEqual(sum(u.consumption for u in usage), 0.04)
        self.assertEqual(len({u.start for u in usage}), len(usage))

    def test_skips_unparseable_rows(self) -> None:
        usage = history.hourly_usage(
            [reading("bad", "1"), reading("13.10.2026 01:00:00", "x"), reading("13.10.2026 02:00:00", "2.0")]
        )
        self.assertEqual(usage, [])


class StatisticsRowsTest(unittest.TestCase):
    def setUp(self) -> None:
        # Hourly usage for 00:00-04:00 UTC: 4, 5, 6, 7 litres.
        self.usage = history.hourly_usage(
            [reading(f"13.10.2026 0{h}:00:00", f"{10 + h * (h + 1) / 2000:.3f}") for h in range(3, 8)]
        )
        self.starts = [u.start.timestamp() for u in self.usage]
        self.before = self.starts[0] - 3600

    def test_first_import_starts_from_zero(self) -> None:
        rows = history.statistics_rows(self.usage, {}, None, self.starts[0])
        self.assertEqual([total for _, total in rows], [0.004, 0.009, 0.015, 0.022])

    def test_appends_only_new_hours_when_unchanged(self) -> None:
        stored = {self.before: 1.0, self.starts[0]: 1.004, self.starts[1]: 1.009}
        rows = history.statistics_rows(self.usage, stored, self.starts[1], self.before)
        self.assertEqual([(h.start.timestamp(), t) for h, t in rows], [(self.starts[2], 1.015), (self.starts[3], 1.022)])

    def test_rewrites_revised_hours(self) -> None:
        # Estimates of 7, 7 litres were stored; the portal now reports 4, 5.
        stored = {self.before: 1.0, self.starts[0]: 1.007, self.starts[1]: 1.014}
        rows = history.statistics_rows(self.usage, stored, self.starts[1], self.before)
        self.assertEqual([t for _, t in rows], [1.004, 1.009, 1.015, 1.022])

    def test_stored_hour_missing_from_portal_is_zeroed(self) -> None:
        extra = self.starts[1] + 1800  # stored row the portal no longer has
        stored = {self.before: 1.0, self.starts[0]: 1.004, extra: 1.02, self.starts[1]: 1.03}
        rows = history.statistics_rows(self.usage, stored, self.starts[3], self.before)
        totals = {h.start.timestamp(): t for h, t in rows}
        self.assertEqual(totals[extra], 1.009)
        self.assertEqual(totals[self.starts[3]], 1.022)

    def test_without_anchor_only_appends(self) -> None:
        stored = {self.starts[1]: 5.0}
        rows = history.statistics_rows(self.usage, stored, self.starts[1], self.before)
        self.assertEqual([t for _, t in rows], [5.006, 5.013])


if __name__ == "__main__":
    unittest.main()
