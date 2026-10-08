"""Incident Cost of Poor Quality estimator.

Reproduces the formulas of the COPQ workbook (``Cost for Poor Quality
Control``, R0) for one incident: downtime, lower production rate, scrap,
C-grade, rework and repack, in thousands of US dollars. The parameters come
from ``copq_estimator_reference.json``; nothing is stored. Formulas are kept as
the workbook writes them, including its unit constants and the rework total
that leaves out the steam and power cost.
"""

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path

from app.quality.cost.schemas import (
    EstimateLineOut,
    EstimateRequest,
    EstimateResponse,
    EstimateStepOut,
    EstimatorAssumptionOut,
    EstimatorProductOut,
    EstimatorReferenceResponse,
    PackageType,
)

REFERENCE_PATH = Path(__file__).with_name("copq_estimator_reference.json")
PACKAGE_TYPES: tuple[PackageType, ...] = ("Bags", "Box", "Single sacks", "Double stack supersacks")

# The workbook's pound conversions, as written in its formulas.
MT_PER_KLB = Decimal("0.454")
LB_PER_KG = Decimal("2.2")
FINISHING_LINES = 2
HOURS_PER_DAY = 24
THOUSAND = Decimal(1000)


class EstimateError(ValueError):
    """The request cannot be estimated (reported to the caller as 422)."""


@dataclass(frozen=True)
class Reference:
    source: str
    fixed_cost_kusd_per_day: Decimal
    gross_margin_usd_per_mt: Decimal
    prime_price: Decimal
    scrap_price: Decimal
    offspec_price: Decimal
    package_price: dict[str, Decimal]
    rework_steam_lb_per_lb: Decimal
    rework_power_kw_per_lb: Decimal
    electricity_usd_per_kw: Decimal
    steam_usd_per_klb: Decimal
    products: dict[str, Decimal]
    guidance: tuple[str, ...]
    notes: tuple[str, ...]


@cache
def reference() -> Reference:
    raw = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    package_price = {k: Decimal(v) for k, v in raw["packagePriceUsdPerPiece"].items()}
    if set(package_price) != set(PACKAGE_TYPES):
        raise ValueError("Estimator reference must price every package type")
    return Reference(
        source=raw["source"],
        fixed_cost_kusd_per_day=Decimal(raw["fixedCostKusdPerDay"]),
        gross_margin_usd_per_mt=Decimal(raw["grossMarginUsdPerMt"]),
        prime_price=Decimal(raw["primePriceUsdPerLb"]),
        scrap_price=Decimal(raw["scrapPriceUsdPerLb"]),
        offspec_price=Decimal(raw["offspecPriceUsdPerLb"]),
        package_price=package_price,
        rework_steam_lb_per_lb=Decimal(raw["reworkSteamLbPerLb"]),
        rework_power_kw_per_lb=Decimal(raw["reworkPowerKwPerLb"]),
        electricity_usd_per_kw=Decimal(raw["electricityUsdPerKw"]),
        steam_usd_per_klb=Decimal(raw["steamUsdPerKlb"]),
        products={p["code"]: Decimal(p["standardRateMtPerDay"]) for p in raw["products"]},
        guidance=tuple(raw["guidance"]),
        notes=tuple(raw["notes"]),
    )


def reference_response() -> EstimatorReferenceResponse:
    ref = reference()
    assumptions = [
        ("Fixed cost", ref.fixed_cost_kusd_per_day, "kUSD per day"),
        ("Gross margin", ref.gross_margin_usd_per_mt, "USD per MT"),
        ("Average prime price", ref.prime_price, "USD per lb"),
        ("Average scrap price", ref.scrap_price, "USD per lb"),
        ("Average off-spec price", ref.offspec_price, "USD per lb"),
        *(
            (f"Package price: {name}", price, "USD per piece")
            for name, price in ref.package_price.items()
        ),
        ("Rework steam", ref.rework_steam_lb_per_lb, "lb steam per lb"),
        ("Rework power", ref.rework_power_kw_per_lb, "kW per lb"),
        ("Electricity", ref.electricity_usd_per_kw, "USD per kW"),
        ("Steam", ref.steam_usd_per_klb, "USD per 1,000 lb"),
    ]
    return EstimatorReferenceResponse(
        source=ref.source,
        products=[
            EstimatorProductOut(code=code, standard_rate_mt_per_day=rate)
            for code, rate in ref.products.items()
        ],
        package_types=list(PACKAGE_TYPES),
        assumptions=[
            EstimatorAssumptionOut(label=label, value=value, unit=unit)
            for label, value, unit in assumptions
        ],
        guidance=list(ref.guidance),
        notes=list(ref.notes),
    )


def _step(label: str, value: Decimal, unit: str) -> EstimateStepOut:
    return EstimateStepOut(label=label, value=value, unit=unit)


def _standard_rate(ref: Reference, product: str | None) -> Decimal:
    if product is None:
        raise EstimateError("Select a product for downtime, lower production rate or rework.")
    if product not in ref.products:
        raise EstimateError(f"Product {product} has no standard rate in the estimator reference.")
    return ref.products[product]


def estimate(request: EstimateRequest) -> EstimateResponse:
    ref = reference()
    lines: list[EstimateLineOut] = []
    warnings: list[str] = []
    days_factor = Decimal(FINISHING_LINES * HOURS_PER_DAY)

    if request.downtime is not None:
        rate = _standard_rate(ref, request.product)
        days = request.downtime.downtime_hours / days_factor
        margin_usd = days * rate * ref.gross_margin_usd_per_mt
        fixed_kusd = days * ref.fixed_cost_kusd_per_day
        lines.append(
            EstimateLineOut(
                code="downtime",
                label="Downtime",
                total_kusd=margin_usd / THOUSAND + fixed_kusd,
                formula=(
                    "Hours ÷ 2 lines ÷ 24 = line-days; line-days × standard rate × margin "
                    "(lost margin) + line-days × fixed cost"
                ),
                steps=[
                    _step("Standard rate", rate, "MT per day"),
                    _step("Line-days down", days, "days"),
                    _step("Lost gross margin", margin_usd, "USD"),
                    _step("Fixed cost", fixed_kusd, "kUSD"),
                ],
            )
        )

    if request.lower_production is not None:
        rate = _standard_rate(ref, request.product)
        lp = request.lower_production
        reduced = rate - lp.flow_rate_lb_per_hour * MT_PER_KLB / THOUSAND * HOURS_PER_DAY
        equivalent_hours = reduced * (lp.hours / HOURS_PER_DAY) / rate * HOURS_PER_DAY
        if equivalent_hours < 0:
            warnings.append(
                "The lower-production flow rate is above the standard rate, which the workbook "
                "turns into a negative cost; lower production rate is counted as 0."
            )
            equivalent_hours = Decimal(0)
        margin_usd = equivalent_hours / HOURS_PER_DAY * rate * ref.gross_margin_usd_per_mt
        fixed_kusd = equivalent_hours / HOURS_PER_DAY * ref.fixed_cost_kusd_per_day
        lines.append(
            EstimateLineOut(
                code="lower_production",
                label="Lower production rate",
                total_kusd=margin_usd / THOUSAND + fixed_kusd,
                formula=(
                    "Equivalent downtime = (standard rate − flow × 0.454 ÷ 1000 × 24) × "
                    "(hours ÷ 24) ÷ standard rate × 24; then lost margin + fixed cost as for "
                    "downtime"
                ),
                steps=[
                    _step("Standard rate", rate, "MT per day"),
                    _step("Equivalent downtime", equivalent_hours, "hours"),
                    _step("Lost gross margin", margin_usd, "USD"),
                    _step("Fixed cost", fixed_kusd, "kUSD"),
                ],
            )
        )

    for code, label, material, price in (
        ("scrap", "Scrap", request.scrap, ref.scrap_price),
        ("c_grade", "C-grade", request.c_grade, ref.offspec_price),
    ):
        if material is None:
            continue
        loss_per_lb = ref.prime_price - price
        lines.append(
            EstimateLineOut(
                code=code,
                label=label,
                total_kusd=material.quantity_lbs * loss_per_lb / THOUSAND,
                formula=f"Pounds × (prime price − {label.lower()} price) ÷ 1000",
                steps=[
                    _step("Quantity", material.quantity_lbs, "lb"),
                    _step("Loss per pound", loss_per_lb, "USD per lb"),
                ],
            )
        )

    if request.rework is not None:
        rate = _standard_rate(ref, request.product)
        rw = request.rework
        hours = rw.quantity_lbs / rw.reworking_rate_lb_per_hour
        fixed_kusd = (
            (hours * rw.production_rate_reduction_lb_per_hour * MT_PER_KLB / THOUSAND)
            / rate
            * ref.fixed_cost_kusd_per_day
        )
        margin_kusd = (
            hours
            * rw.production_rate_reduction_lb_per_hour
            / LB_PER_KG
            / THOUSAND
            * ref.gross_margin_usd_per_mt
            / THOUSAND
        )
        price = ref.package_price[rw.package_type]
        packaging_kusd = rw.quantity_lbs / rw.package_load_lb_per_piece * price / THOUSAND
        energy_kusd = (
            ref.electricity_usd_per_kw * ref.rework_power_kw_per_lb * rw.quantity_lbs
            + ref.steam_usd_per_klb * ref.rework_steam_lb_per_lb * rw.quantity_lbs / THOUSAND
        ) / THOUSAND
        lines.append(
            EstimateLineOut(
                code="rework",
                label="Rework",
                total_kusd=packaging_kusd + fixed_kusd + margin_kusd,
                formula=(
                    "Fixed-cost write-off + lost margin while production is reduced + new "
                    "packaging (steam and power cost not included, as in the workbook)"
                ),
                steps=[
                    _step("Rework time", hours, "hours"),
                    _step("Fixed-cost write-off", fixed_kusd, "kUSD"),
                    _step("Lost gross margin", margin_kusd, "kUSD"),
                    _step("Packaging", packaging_kusd, "kUSD"),
                    _step("Steam and power (not in total)", energy_kusd, "kUSD"),
                ],
            )
        )

    if request.repack is not None:
        rp = request.repack
        price = ref.package_price[rp.package_type]
        pieces = (rp.quantity_lbs / rp.package_load_lb_per_piece).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
        packaging_kusd = pieces * price / THOUSAND
        overtime_kusd = rp.extra_persons * rp.overtime_hours_per_person * rp.pay_rate_usd_per_hour
        overtime_kusd /= THOUSAND
        lines.append(
            EstimateLineOut(
                code="repack",
                label="Repack",
                total_kusd=packaging_kusd + overtime_kusd,
                formula="Pieces (rounded) × package price + persons × hours × pay rate",
                steps=[
                    _step("Pieces", pieces, "pieces"),
                    _step("Packaging", packaging_kusd, "kUSD"),
                    _step("Overtime", overtime_kusd, "kUSD"),
                ],
            )
        )

    total_kusd = sum((line.total_kusd for line in lines), Decimal(0))
    return EstimateResponse(
        lines=lines,
        total_kusd=total_kusd,
        total_usd=total_kusd * THOUSAND,
        warnings=warnings,
        source=ref.source,
    )
