"""Invoice estimate from Apavital invoices and official meter readings.

Kept free of Home Assistant imports so the logic can be unit tested on its own.

Apavital bills the water measured between two official meter readings. The
price per m³ is learned from recent invoices (amount / m³ billed), and the next
invoice is estimated from the water used since the last official reading.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

_DATE_FORMATS = (
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M:%S",
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y",
)
MAX_INVOICES_FOR_PRICE = 3


@dataclass(frozen=True)
class Invoice:
    """One Apavital invoice."""

    number: str
    issued: date
    due: date | None
    amount: float  # RON


@dataclass(frozen=True)
class OfficialReading:
    """A meter reading Apavital billed from."""

    day: date
    index: float  # m³


@dataclass(frozen=True)
class BillingEstimate:
    """Estimated value of the next invoice."""

    amount: float  # RON
    price_per_m3: float  # RON / m³
    consumption_m3: float  # used since the last official reading
    since: date  # date of the last official reading
    invoices_used: int


def as_list(value: Any) -> list[dict]:
    """Return the rows of an API response that may be wrapped in {"data": [...]}."""
    if isinstance(value, dict):
        value = value.get("data")
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def parse_date(value: Any) -> date | None:
    """Parse the date formats the Apavital portal uses."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def parse_amount(value: Any) -> float | None:
    """Parse an amount written as 123.45, 123,45 or 1.234,56."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("RON", "").replace("lei", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_invoices(rows: list[dict]) -> list[Invoice]:
    """Invoices with a date and an amount, oldest first."""
    invoices = []
    for row in rows:
        issued = parse_date(row.get("DATA"))
        amount = parse_amount(row.get("VALOARE"))
        if issued is None or amount is None:
            continue
        invoices.append(
            Invoice(
                number=str(row.get("FACTURA") or ""),
                issued=issued,
                due=parse_date(row.get("SCADENTA")),
                amount=amount,
            )
        )
    return sorted(invoices, key=lambda invoice: invoice.issued)


def parse_official_readings(rows: list[dict]) -> list[OfficialReading]:
    """Official readings, oldest first, one per day."""
    by_day: dict[date, float] = {}
    for row in rows:
        day = parse_date(row.get("DATA"))
        index = parse_amount(row.get("INDEX_CITIT"))
        if day is not None and index is not None:
            by_day[day] = max(index, by_day.get(day, index))
    return [OfficialReading(day, index) for day, index in sorted(by_day.items())]


def billed_prices(
    invoices: list[Invoice], readings: list[OfficialReading]
) -> list[float]:
    """Price per m³ of recent invoices, newest first.

    An invoice bills the water between the last official reading on or before
    its date and the reading before that.
    """
    prices = []
    for invoice in reversed(invoices):
        before = [r for r in readings if r.day <= invoice.issued]
        if len(before) < 2:
            continue
        billed = before[-1].index - before[-2].index
        if billed > 0 and invoice.amount > 0:
            prices.append(invoice.amount / billed)
        if len(prices) == MAX_INVOICES_FOR_PRICE:
            break
    return prices


def estimate_next_invoice(
    invoices: list[Invoice], readings: list[OfficialReading], current_index: float | None
) -> BillingEstimate | None:
    """Estimate the next invoice, or None without enough history."""
    prices = billed_prices(invoices, readings)
    if not prices or not readings or current_index is None:
        return None
    price = statistics.median(prices)
    last = readings[-1]
    used = max(0.0, current_index - last.index)
    return BillingEstimate(
        amount=round(used * price, 2),
        price_per_m3=round(price, 2),
        consumption_m3=round(used, 3),
        since=last.day,
        invoices_used=len(prices),
    )
