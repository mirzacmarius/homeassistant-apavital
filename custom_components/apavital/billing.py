"""Invoice estimate from Apavital invoices and official meter readings.

Kept free of Home Assistant imports so the logic can be unit tested on its own.

Apavital reads every meter on a contract around the same day each month and
bills that water the following month, together with sewage, on one invoice for
all the places of the contract. The latest invoice gives the price of one m³ of
water; each place's cost is its own meter's water times that price.
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
RECENT_MONTHS = 3  # averaged before the reading of the next invoice exists


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
    address: str = ""


@dataclass(frozen=True)
class WaterPrice:
    """Price of one m³ of water, sewage included, from the latest invoice."""

    per_m3: float  # RON per m³ of water read on the meters
    invoice: Invoice
    water_m3: float  # water of the reading month the invoice billed, all meters


@dataclass(frozen=True)
class Share:
    """What one meter costs on an invoice of the whole contract."""

    amount: float  # RON
    water_m3: float  # the meter's water in the reading month billed
    month: tuple[int, int]  # (year, month) of the invoice
    from_readings: bool  # False when water_m3 is an average of recent months


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
                address=str(row.get("ADRESA") or "").strip(),
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


def water_price(invoices: list[Invoice], readings: list[OfficialReading]) -> WaterPrice | None:
    """Price per m³ of water from the latest invoice that matches the readings.

    An invoice issued in month M bills the water read in month M-1 on every
    meter of the contract, so its amount divided by that water is the price of
    one m³ of water, sewage and VAT included.
    """
    water = water_by_reading_month(readings)
    for invoice in reversed(invoices):
        read = water.get(_previous_month(_month(invoice.issued)))
        if read and invoice.amount > 0:
            return WaterPrice(per_m3=round(invoice.amount / read, 4), invoice=invoice, water_m3=read)
    return None


def own_meter(
    readings: list[OfficialReading], meter_serial: str | None, places: list[dict]
) -> str | None:
    """The meter of this config entry's place.

    That is the smart meter whose usage the integration reads; failing that,
    the meter at the address of the contract's first place.
    """
    meters = {reading.meter for reading in readings}
    if meter_serial and meter_serial in meters:
        return meter_serial
    if len(meters) == 1:
        return next(iter(meters))
    numbered = sorted(places, key=lambda place: parse_amount(place.get("LOCCONS_NR")) or 0)
    address = str(numbered[0].get("ADRESA") or "").strip() if numbered else ""
    at_address = {reading.meter for reading in readings if address and reading.address == address}
    return next(iter(at_address)) if len(at_address) == 1 else None


def last_invoice_share(
    price: WaterPrice, readings: list[OfficialReading], meter: str
) -> Share:
    """The meter's part of the latest invoice."""
    month = _month(price.invoice.issued)
    water = water_by_reading_month([r for r in readings if r.meter == meter])
    used = water.get(_previous_month(month), 0.0)
    return Share(round(used * price.per_m3, 2), used, month, True)


def next_invoice_share(
    price: WaterPrice, readings: list[OfficialReading], meter: str
) -> Share:
    """Estimate of the meter's part of the next invoice.

    It bills the last reading month; until that reading exists the average of
    the meter's recent months is used.
    """
    month = _next_month(_month(price.invoice.issued))
    water = water_by_reading_month([r for r in readings if r.meter == meter])
    used = water.get(_previous_month(month))
    from_readings = used is not None
    if used is None:
        recent = [water[m] for m in sorted(water)[-RECENT_MONTHS:]]
        used = statistics.mean(recent) if recent else 0.0
    return Share(round(used * price.per_m3, 2), round(used, 3), month, from_readings)
