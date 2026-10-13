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


if __name__ == "__main__":
    unittest.main()
