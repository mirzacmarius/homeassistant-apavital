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

INVOICES = [
    {"FACTURA": "A1", "DATA": "05.08.2026", "SCADENTA": "05.09.2026", "VALOARE": "150,00"},
    {"FACTURA": "A2", "DATA": "05.09.2026", "SCADENTA": "05.10.2026", "VALOARE": "151,50"},
    {"FACTURA": "A3", "DATA": "06.10.2026", "SCADENTA": "06.11.2026", "VALOARE": "80,80"},
]
READINGS = [
    {"DATA": "01.07.2026", "INDEX_CITIT": "40"},
    {"DATA": "01.08.2026", "INDEX_CITIT": "50"},  # 10 m³ -> 150 RON
    {"DATA": "01.09.2026", "INDEX_CITIT": "60"},  # 10 m³ -> 151.5 RON
    {"DATA": "01.10.2026", "INDEX_CITIT": "65,5"},  # 5.5 m³ -> 80.8 RON
]


class ParseTest(unittest.TestCase):
    def test_amounts(self) -> None:
        self.assertEqual(billing.parse_amount("1.234,56"), 1234.56)
        self.assertEqual(billing.parse_amount("123,45"), 123.45)
        self.assertEqual(billing.parse_amount("123.45"), 123.45)
        self.assertEqual(billing.parse_amount(42), 42.0)
        self.assertIsNone(billing.parse_amount("n/a"))

    def test_dates(self) -> None:
        self.assertEqual(billing.parse_date("05.10.2026"), date(2026, 10, 5))
        self.assertEqual(billing.parse_date("2026-10-05T00:00:00"), date(2026, 10, 5))
        self.assertIsNone(billing.parse_date("soon"))

    def test_wrapped_and_unsorted_rows(self) -> None:
        rows = billing.as_list({"data": list(reversed(INVOICES)) + ["junk"]})
        invoices = billing.parse_invoices(rows)
        self.assertEqual([i.number for i in invoices], ["A1", "A2", "A3"])
        self.assertEqual(invoices[-1].due, date(2026, 11, 6))


class EstimateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.invoices = billing.parse_invoices(INVOICES)
        self.readings = billing.parse_official_readings(READINGS)

    def test_price_per_m3_from_recent_invoices(self) -> None:
        prices = billing.billed_prices(self.invoices, self.readings)
        self.assertEqual([round(p, 2) for p in prices], [14.69, 15.15, 15.0])

    def test_estimate_since_last_official_reading(self) -> None:
        estimate = billing.estimate_next_invoice(self.invoices, self.readings, 65.82)
        self.assertEqual(estimate.since, date(2026, 10, 1))
        self.assertEqual(estimate.price_per_m3, 15.0)  # median
        self.assertEqual(estimate.consumption_m3, 0.32)
        self.assertEqual(estimate.amount, 4.8)
        self.assertEqual(estimate.invoices_used, 3)

    def test_no_estimate_without_billed_quantity(self) -> None:
        readings = billing.parse_official_readings(READINGS[:1])
        self.assertIsNone(billing.estimate_next_invoice(self.invoices, readings, 65.82))
        self.assertIsNone(billing.estimate_next_invoice(self.invoices, self.readings, None))


if __name__ == "__main__":
    unittest.main()
