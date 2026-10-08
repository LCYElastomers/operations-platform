"""The incidence-rate formula shared by Safety Performance and TRIR Experience.

    rate = events × 200,000 ÷ worked hours

200,000 hours is 100 full-time workers × 40 hours × 50 weeks (the OSHA
basis). Rates are computed in Decimal at full precision and rounded only for
display. A rate with unknown, zero or negative hours does not exist (None);
it is never shown as 0.
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

RATE_BASE = 200_000
DISPLAY_PLACES = 2
# Two rates are "equal" when they differ by less than half a unit in the second
# decimal place, i.e. when they display the same at two decimals.
COMPARISON_TOLERANCE = Decimal("0.005")
_PRECISION = 34

Comparison = Literal["below", "equal", "above", "unavailable"]


def incidence_rate(events: int | None, hours: Decimal | None) -> Decimal | None:
    if events is None or hours is None or hours <= 0:
        return None
    with localcontext() as context:
        context.prec = _PRECISION
        return Decimal(events) * RATE_BASE / hours


def display_rate(rate: Decimal | None) -> str | None:
    if rate is None:
        return None
    return str(rate.quantize(Decimal(1).scaleb(-DISPLAY_PLACES), rounding=ROUND_HALF_UP))


def formula_text(events: int | None, hours: Decimal | None) -> str | None:
    """The calculation with its inputs, e.g. ``(1 × 200,000) ÷ 145,194``."""
    if events is None or hours is None or hours <= 0:
        return None
    shown = f"{hours:,.2f}".removesuffix(".00")
    return f"({events:,} × {RATE_BASE:,}) ÷ {shown}"


def compare(rate: Decimal | None, benchmark: Decimal | None) -> Comparison:
    if rate is None or benchmark is None:
        return "unavailable"
    difference = rate - benchmark
    if abs(difference) < COMPARISON_TOLERANCE:
        return "equal"
    return "below" if difference < 0 else "above"
