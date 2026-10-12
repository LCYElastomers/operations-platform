"""The one look shared by every PDF and Excel export."""

import datetime as dt
from decimal import Decimal

from app.reports.model import Value, ValueType
from app.safety.site_calendar import SITE_TIME_ZONE

PRODUCT = "Operations-Platform"
HEADER = "OPERATIONS-PLATFORM"

INK = "#0f172a"
MUTED = "#64748b"
RULE = "#cbd5e1"
HEADER_FILL = "#1e293b"
HEADER_TEXT = "#ffffff"
STRIPE = "#f1f5f9"
KPI_FILL = "#f8fafc"
ACCENT = "#2563eb"

SERIES_COLORS = ["#2563eb", "#059669", "#dc2626", "#ea580c", "#7c3aed", "#0d9488", "#64748b"]

NOT_RECORDED = "—"

EXCEL_FORMATS: dict[ValueType, str] = {
    "text": "@",
    "int": "#,##0",
    "decimal": "#,##0.00",
    "money": '"$"#,##0.00;[Red]-"$"#,##0.00',
    "money4": '"$"#,##0.0000',
    "percent": "0.0%",
    "date": "yyyy-mm-dd",
    "datetime": "yyyy-mm-dd hh:mm",
}


def site_time(instant: dt.datetime) -> dt.datetime:
    return instant.astimezone(SITE_TIME_ZONE)


def generated_label(instant: dt.datetime) -> str:
    local = site_time(instant)
    return f"{local:%b} {local.day}, {local.year} {local:%H:%M} {local.tzname()}"


def display(value: Value, kind: ValueType) -> str:
    """A value as text for the PDF. Percentages are fractions (0.125 is 12.5%)."""
    if value is None or value == "":
        return NOT_RECORDED
    if kind in ("money", "money4"):
        amount = Decimal(str(value))
        sign = "-" if amount < 0 else ""
        places = 4 if kind == "money4" else 2
        return f"{sign}${abs(amount):,.{places}f}"
    if kind == "percent":
        return f"{Decimal(str(value)) * 100:,.1f}%"
    if kind == "int" and isinstance(value, int | float | Decimal):
        return f"{int(value):,}"
    if kind == "decimal" and isinstance(value, int | float | Decimal):
        return f"{Decimal(str(value)):,.2f}"
    if isinstance(value, dt.datetime):
        local = site_time(value) if value.tzinfo else value
        return f"{local:%Y-%m-%d %H:%M}"
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)
