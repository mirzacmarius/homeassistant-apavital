"""Tests for the invoice estimate (no Home Assistant needed).

Run with: python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
import unittest

_PATH = Path(__file__).parents[1] / "custom_components" / "apavital" / "billing.py"
_SPEC = importlib.util.spec_from_file_location("apavital_billing", _PATH)
billing = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = billing
_SPEC.loader.exec_module(billing)

REGULAR = "Citire de regularizare"
MOVE = "Citire la miscare contor"


def reading(day: str, meter: str, index: str, kind: str = REGULAR) -> dict:
    return {"DATA": day, "SERIA": meter, "INDEX_CITIT": index, "TIP_CITIRE": kind}


# Two meters read on the 4th; each invoice bills the previous month's reading × 1.8.
READINGS = [
    reading("04.07.2026", "A", "10"), reading("04.07.2026", "B", "100"),
    reading("04.08.2026", "A", "20"), reading("04.08.2026", "B", "110"),  # 20 m³
    reading("04.09.2026", "A", "26"), reading("04.09.2026", "B", "120"),  # 16 m³
    reading("04.10.2026", "A", "40"), reading("04.10.2026", "B", "130"),  # 24 m³
]
INVOICES = [
    {"FACTURA": "F1", "DATA": "10.09.2026", "SCADENTA": "25.09.2026", "CONSUM": "36", "VALOARE": "429.48"},
    {"FACTURA": "F2", "DATA": "12.10.2026", "SCADENTA": "27.10.2026", "CONSUM": "28.8", "VALOARE": "343.58"},
]


class ParseTest(unittest.TestCase):
    def test_amounts(self) -> None:
        self.assertEqual(billing.parse_amount("1.234,56"), 1234.56)
        self.assertEqual(billing.parse_amount("1,194.93"), 1194.93)
        self.assertEqual(billing.parse_amount("123,45"), 123.45)
        self.assertEqual(billing.parse_amount("607.80"), 607.8)
        self.assertEqual(billing.parse_amount(42), 42.0)
        self.assertIsNone(billing.parse_amount("n/a"))

    def test_dates(self) -> None:
        self.assertEqual(billing.parse_date("05.10.2026"), date(2026, 10, 5))
        self.assertEqual(billing.parse_date("2026-10-05T00:00:00"), date(2026, 10, 5))
        self.assertIsNone(billing.parse_date("soon"))

    def test_wrapped_and_unsorted_invoices(self) -> None:
        invoices = billing.parse_invoices(billing.as_list({"data": list(reversed(INVOICES)) + ["x"]}))
        self.assertEqual([i.number for i in invoices], ["F1", "F2"])
        self.assertEqual(invoices[-1].billed_m3, 28.8)


class WaterByReadingMonthTest(unittest.TestCase):
    def test_sums_meters_per_reading_month(self) -> None:
        water = billing.water_by_reading_month(billing.parse_official_readings(READINGS))
        self.assertEqual(water, {(2026, 8): 20.0, (2026, 9): 16.0, (2026, 10): 24.0})

    def test_meter_replacement_keeps_both_meters_usage(self) -> None:
        readings = billing.parse_official_readings([
            reading("14.03.2026", "A", "932"),
            reading("23.03.2026", "A", "0", MOVE),
            reading("23.03.2026", "A", "934", MOVE),
            reading("16.04.2026", "A", "6"),
        ])
        self.assertEqual(billing.water_by_reading_month(readings), {(2026, 4): 8.0})


class EstimateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.invoices = billing.parse_invoices(INVOICES)
        self.readings = billing.parse_official_readings(READINGS)

    def test_next_invoice_bills_last_reading_month(self) -> None:
        estimate = billing.estimate_next_invoice(self.invoices, self.readings)
        self.assertEqual(estimate.month, (2026, 11))
        self.assertTrue(estimate.from_readings)
        self.assertEqual(estimate.water_m3, 24.0)
        self.assertEqual(estimate.factor, 1.8)
        self.assertEqual(estimate.billed_m3, 43.2)
        self.assertAlmostEqual(estimate.amount, 43.2 * 11.93, places=1)

    def test_falls_back_to_recent_average_before_readings(self) -> None:
        estimate = billing.estimate_next_invoice(self.invoices, self.readings[:-2])
        self.assertFalse(estimate.from_readings)
        self.assertEqual(estimate.water_m3, 18.0)

    def test_no_estimate_without_matching_readings(self) -> None:
        self.assertIsNone(billing.estimate_next_invoice(self.invoices, []))
        self.assertIsNone(billing.estimate_next_invoice([], self.readings))


if __name__ == "__main__":
    unittest.main()
