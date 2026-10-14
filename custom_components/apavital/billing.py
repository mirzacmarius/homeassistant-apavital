"""Invoice estimate from Apavital invoices and official meter readings.

Kept free of Home Assistant imports so the logic can be unit tested on its own.

Apavital reads every meter on a contract around the same day each month and
bills that water the following month, together with sewage. The next invoice
is estimated from the official readings it will bill, using the factor and the
price per billed m³ of recent invoices.
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
    billed_m3: float | None  # CONSUM: water + sewage quantity billed


@dataclass(frozen=True)
class OfficialReading:
    """A meter reading Apavital billed from."""

    day: date
    meter: str
    index: float  # m³
    regular: bool  # False for readings taken when a meter is replaced


@dataclass(frozen=True)
class BillingEstimate:
    """Estimated value of the next invoice."""

    amount: float  # RON
    month: tuple[int, int]  # (year, month) the invoice is expected in
    water_m3: float  # water of the reading month it bills, all meters
    billed_m3: float  # water_m3 × factor, the invoice's CONSUM
    factor: float  # billed m³ per m³ of water (water + sewage)
    price_per_billed_m3: float  # RON
    from_readings: bool  # False when water_m3 is an average of recent months
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
    """Parse an amount written as 123.45, 123,45, 1,234.56 or 1.234,56."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("RON", "").replace("lei", "")
    if "," in text and "." in text:
        if text.rindex(",") > text.rindex("."):  # 1.234,56
            text = text.replace(".", "").replace(",", ".")
        else:  # 1,234.56
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_invoices(rows: list[dict]) -> list[Invoice]:
    """Invoices with a date, an amount and the quantity billed, oldest first."""
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
                billed_m3=parse_amount(row.get("CONSUM")),
            )
        )
    return sorted(invoices, key=lambda invoice: invoice.issued)


def parse_official_readings(rows: list[dict]) -> list[OfficialReading]:
    """Official readings of every meter on the contract."""
    readings = []
    for row in rows:
        day = parse_date(row.get("DATA"))
        index = parse_amount(row.get("INDEX_CITIT"))
        if day is None or index is None:
            continue
        readings.append(
            OfficialReading(
                day=day,
                meter=str(row.get("SERIA") or ""),
                index=index,
                regular="regularizare" in str(row.get("TIP_CITIRE") or "").lower(),
            )
        )
    return readings


def _month(day: date) -> tuple[int, int]:
    return (day.year, day.month)


def _previous_month(month: tuple[int, int]) -> tuple[int, int]:
    year, number = month
    return (year - 1, 12) if number == 1 else (year, number - 1)


def _next_month(month: tuple[int, int]) -> tuple[int, int]:
    year, number = month
    return (year + 1, 1) if number == 12 else (year, number + 1)


def water_by_reading_month(readings: list[OfficialReading]) -> dict[tuple[int, int], float]:
    """Water of all meters, per month of the regular reading that closed it.

    A meter replacement is read twice on the same day (final index of the old
    meter, then 0 for the new one); the usage of both meters is kept.
    """
    by_meter: dict[str, list[OfficialReading]] = {}
    for reading in readings:
        by_meter.setdefault(reading.meter, []).append(reading)

    water: dict[tuple[int, int], float] = {}
    for meter_readings in by_meter.values():
        meter_readings.sort(key=lambda r: (r.day, -r.index))
        previous: float | None = None
        used = 0.0
        for reading in meter_readings:
            if previous is not None:
                used += reading.index - previous if reading.index >= previous else reading.index
            previous = reading.index
            if reading.regular:
                if used or reading is not meter_readings[0]:
                    month = _month(reading.day)
                    water[month] = round(water.get(month, 0.0) + used, 3)
                used = 0.0
    return water


def estimate_next_invoice(
    invoices: list[Invoice], readings: list[OfficialReading]
) -> BillingEstimate | None:
    """Estimate the next invoice, or None without enough history.

    An invoice issued in month M bills the water read in month M-1, times a
    factor for sewage (1.8 for Apavital households). The factor and the price
    per billed m³ are learned from the last invoices.
    """
    water = water_by_reading_month(readings)
    factors, prices = [], []
    for invoice in reversed(invoices):
        if not invoice.billed_m3 or invoice.amount <= 0:
            continue
        prices.append(invoice.amount / invoice.billed_m3)
        read = water.get(_previous_month(_month(invoice.issued)))
        if read:
            factors.append(invoice.billed_m3 / read)
        if len(prices) == MAX_INVOICES_FOR_PRICE:
            break
    if not prices or not factors:
        return None

    month = _next_month(_month(invoices[-1].issued))
    water_m3 = water.get(_previous_month(month))
    from_readings = water_m3 is not None
    if water_m3 is None:
        recent = [water[m] for m in sorted(water)[-MAX_INVOICES_FOR_PRICE:]]
        water_m3 = statistics.mean(recent) if recent else 0.0
    factor = statistics.median(factors)
    price = statistics.median(prices)
    billed = water_m3 * factor
    return BillingEstimate(
        amount=round(billed * price, 2),
        month=month,
        water_m3=round(water_m3, 3),
        billed_m3=round(billed, 3),
        factor=round(factor, 3),
        price_per_billed_m3=round(price, 4),
        from_readings=from_readings,
        invoices_used=len(prices),
    )
