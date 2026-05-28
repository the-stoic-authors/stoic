"""Stoic ELN — Per-substance reports.

Three views, computed for one substance over a selectable period:

1. **Consumption** — how much of the substance was consumed in the
   period, broken down by source (reaction runs, run-step components,
   mixture preparations). Reported separately per unit (g and mL),
   never converting between them via density — a substance consumed
   "125 g + 40 mL" is shown as such, because density is not always
   known and converting would hide the real measured figures.

2. **Stock coverage** (the "turnover" view) — average daily
   consumption over the period, current active stock, and an
   estimated "stock will last ~N days at the current rate". This
   replaces the original "days from purchase to depletion" idea
   because InventoryItem has no depletion timestamp; daily-rate +
   coverage uses data we actually have (dated consumption events).

3. **Cost trend** — unit price (€/g or €/mL) of each lot over time,
   plus a per-supplier breakdown (avg/min/max). Each lot is a real
   price point at its purchase date.

All money is in the configured currency; we read the raw EUR-named
fields (historical naming) and format via the currency filter in the
template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func

from stoic_eln.extensions import db
from stoic_eln.models import (
    InventoryItem,
    MixturePrep,
    MixturePrepConsumption,
    Run,
    RunComponent,
    RunStep,
    RunStepComponent,
    Substance,
)
from stoic_eln.models.run import STATUS_COMPLETED


# ── Data structures ─────────────────────────────────────────────────


@dataclass
class ConsumptionBySource:
    """Consumption totals for one source (runs / steps / preps),
    split by unit. Either or both of g/mL may be populated."""

    source: str  # 'runs' | 'run_steps' | 'preps'
    total_g: float = 0.0
    total_mL: float = 0.0
    event_count: int = 0


@dataclass
class ConsumptionView:
    """Vista 1 — consumption over the period."""

    by_source: list[ConsumptionBySource] = field(default_factory=list)

    @property
    def total_g(self) -> float:
        return sum(s.total_g for s in self.by_source)

    @property
    def total_mL(self) -> float:
        return sum(s.total_mL for s in self.by_source)

    @property
    def has_data(self) -> bool:
        return self.total_g > 0 or self.total_mL > 0


@dataclass
class CoverageView:
    """Vista 2 — average daily consumption + stock coverage estimate."""

    period_days: int
    consumed_g: float
    consumed_mL: float
    daily_g: float | None  # consumed_g / period_days, or None if no data
    daily_mL: float | None
    stock_g: float  # current active stock
    stock_mL: float
    coverage_days_g: float | None  # stock_g / daily_g, or None
    coverage_days_mL: float | None
    enough_data: bool  # True if we have a meaningful daily rate


@dataclass
class LotPricePoint:
    """One lot as a price point in the cost-trend chart."""

    lot_id: int
    batch_code: str | None
    purchased_at: date | None
    supplier: str | None
    unit_price: float | None  # € per g or per mL
    unit: str  # 'g' | 'mL' | ''


@dataclass
class SupplierCost:
    """Per-supplier cost aggregate for the cost-trend table."""

    supplier: str
    lot_count: int
    avg_price: float
    min_price: float
    max_price: float
    unit: str


@dataclass
class CostTrendView:
    """Vista 3 — unit price over time + per-supplier breakdown."""

    points: list[LotPricePoint] = field(default_factory=list)
    by_supplier: list[SupplierCost] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return any(p.unit_price is not None for p in self.points)


@dataclass
class SubstanceReport:
    """Full per-substance report bundle."""

    substance: Substance
    date_from: date
    date_to: date
    consumption: ConsumptionView
    coverage: CoverageView
    cost_trend: CostTrendView


# ── Computation ─────────────────────────────────────────────────────


def _as_date(d: datetime | date | None) -> date | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    return d


def _consumption_from_runs(
    substance_id: int,
    date_from: date,
    date_to: date,
) -> ConsumptionBySource:
    """Sum actual_mass_g / actual_volume_mL from RunComponent rows of
    completed runs whose completion date falls in the window."""
    q = (
        db.session.query(
            func.coalesce(func.sum(RunComponent.actual_mass_g), 0.0),
            func.coalesce(func.sum(RunComponent.actual_volume_mL), 0.0),
            func.count(RunComponent.id),
        )
        .join(Run, RunComponent.run_id == Run.id)
        .filter(
            RunComponent.substance_id == substance_id,
            Run.status == STATUS_COMPLETED,
            Run.completed_at.isnot(None),
            func.date(Run.completed_at) >= date_from,
            func.date(Run.completed_at) <= date_to,
        )
    )
    total_g, total_mL, n = q.one()
    return ConsumptionBySource(
        source="runs",
        total_g=float(total_g or 0.0),
        total_mL=float(total_mL or 0.0),
        event_count=int(n or 0),
    )


def _consumption_from_run_steps(
    substance_id: int,
    date_from: date,
    date_to: date,
) -> ConsumptionBySource:
    """Sum from RunStepComponent rows of completed runs in the window."""
    q = (
        db.session.query(
            func.coalesce(func.sum(RunStepComponent.actual_mass_g), 0.0),
            func.coalesce(func.sum(RunStepComponent.actual_volume_mL), 0.0),
            func.count(RunStepComponent.id),
        )
        .join(RunStep, RunStepComponent.step_id == RunStep.id)
        .join(Run, RunStep.run_id == Run.id)
        .filter(
            RunStepComponent.substance_id == substance_id,
            Run.status == STATUS_COMPLETED,
            Run.completed_at.isnot(None),
            func.date(Run.completed_at) >= date_from,
            func.date(Run.completed_at) <= date_to,
        )
    )
    total_g, total_mL, n = q.one()
    return ConsumptionBySource(
        source="run_steps",
        total_g=float(total_g or 0.0),
        total_mL=float(total_mL or 0.0),
        event_count=int(n or 0),
    )


def _consumption_from_preps(
    substance_id: int,
    date_from: date,
    date_to: date,
) -> ConsumptionBySource:
    """Sum MixturePrepConsumption where the consumed lot is of this
    substance, for preps created in the window.

    quantity_consumed is stored with a per-row unit; we bucket g/kg
    into grams and mL/L into millilitres. (kg/L normalisation matches
    the convention used elsewhere in prep_service cost imputation.)
    """
    rows = (
        db.session.query(
            MixturePrepConsumption.quantity_consumed,
            MixturePrepConsumption.quantity_unit,
        )
        .join(MixturePrep, MixturePrepConsumption.prep_id == MixturePrep.id)
        .join(InventoryItem, MixturePrepConsumption.inventory_item_id == InventoryItem.id)
        .filter(
            InventoryItem.substance_id == substance_id,
            func.date(MixturePrep.created_at) >= date_from,
            func.date(MixturePrep.created_at) <= date_to,
        )
        .all()
    )
    total_g = 0.0
    total_mL = 0.0
    n = 0
    for qty, unit in rows:
        if qty is None:
            continue
        n += 1
        u = (unit or "").lower()
        if u == "kg":
            total_g += qty * 1000.0
        elif u == "g":
            total_g += qty
        elif u == "l":
            total_mL += qty * 1000.0
        elif u == "ml":
            total_mL += qty
        # other units (mol, etc.) are ignored for this g/mL split
    return ConsumptionBySource(
        source="preps",
        total_g=total_g,
        total_mL=total_mL,
        event_count=n,
    )


def _current_stock(substance_id: int) -> tuple[float, float]:
    """Current active stock of a substance, summed across active lots."""
    g, mL = (
        db.session.query(
            func.coalesce(func.sum(InventoryItem.quantity_g), 0.0),
            func.coalesce(func.sum(InventoryItem.quantity_mL), 0.0),
        )
        .filter(
            InventoryItem.substance_id == substance_id,
            InventoryItem.is_active.is_(True),
        )
        .one()
    )
    return float(g or 0.0), float(mL or 0.0)


def _cost_trend(substance_id: int, date_from: date, date_to: date) -> CostTrendView:
    """Per-lot price points + per-supplier aggregates.

    Lots are filtered to the window by purchase date. Lots without a
    purchase date or without a derivable unit price still appear as
    points (with unit_price=None) so the operator sees the gap, but
    they're excluded from supplier aggregates.
    """
    lots = (
        db.session.query(InventoryItem)
        .filter(
            InventoryItem.substance_id == substance_id,
            InventoryItem.purchased_at.isnot(None),
            InventoryItem.purchased_at >= date_from,
            InventoryItem.purchased_at <= date_to,
        )
        .order_by(InventoryItem.purchased_at.asc(), InventoryItem.id.asc())
        .all()
    )

    points: list[LotPricePoint] = []
    # supplier -> list of (price, unit)
    by_sup: dict[str, list[tuple[float, str]]] = {}

    for lot in lots:
        price = lot.cost_per_unit  # € per g or per mL, or None
        unit = lot.cost_per_unit_unit.lstrip("/") if price is not None else ""
        points.append(
            LotPricePoint(
                lot_id=lot.id,
                batch_code=lot.batch_code,
                purchased_at=lot.purchased_at,
                supplier=lot.supplier,
                unit_price=price,
                unit=unit,
            )
        )
        if price is not None and lot.supplier:
            by_sup.setdefault(lot.supplier, []).append((price, unit))

    suppliers: list[SupplierCost] = []
    for sup, entries in sorted(by_sup.items()):
        prices = [p for p, _ in entries]
        # Use the most common unit among this supplier's lots
        unit = entries[0][1] if entries else ""
        suppliers.append(
            SupplierCost(
                supplier=sup,
                lot_count=len(prices),
                avg_price=sum(prices) / len(prices),
                min_price=min(prices),
                max_price=max(prices),
                unit=unit,
            )
        )

    return CostTrendView(points=points, by_supplier=suppliers)


def compute_substance_report(
    substance_id: int,
    *,
    date_from: date,
    date_to: date,
) -> SubstanceReport | None:
    """Build the full per-substance report for the given window.

    Returns None if the substance does not exist.
    """
    substance = db.session.get(Substance, substance_id)
    if substance is None:
        return None

    # Vista 1 — consumption
    runs = _consumption_from_runs(substance_id, date_from, date_to)
    steps = _consumption_from_run_steps(substance_id, date_from, date_to)
    preps = _consumption_from_preps(substance_id, date_from, date_to)
    consumption = ConsumptionView(by_source=[runs, steps, preps])

    # Vista 2 — coverage
    period_days = max((date_to - date_from).days, 1)
    consumed_g = consumption.total_g
    consumed_mL = consumption.total_mL
    daily_g = consumed_g / period_days if consumed_g > 0 else None
    daily_mL = consumed_mL / period_days if consumed_mL > 0 else None
    stock_g, stock_mL = _current_stock(substance_id)
    coverage_days_g = (stock_g / daily_g) if daily_g and daily_g > 0 else None
    coverage_days_mL = (stock_mL / daily_mL) if daily_mL and daily_mL > 0 else None
    coverage = CoverageView(
        period_days=period_days,
        consumed_g=consumed_g,
        consumed_mL=consumed_mL,
        daily_g=daily_g,
        daily_mL=daily_mL,
        stock_g=stock_g,
        stock_mL=stock_mL,
        coverage_days_g=coverage_days_g,
        coverage_days_mL=coverage_days_mL,
        enough_data=(daily_g is not None or daily_mL is not None),
    )

    # Vista 3 — cost trend
    cost_trend = _cost_trend(substance_id, date_from, date_to)

    return SubstanceReport(
        substance=substance,
        date_from=date_from,
        date_to=date_to,
        consumption=consumption,
        coverage=coverage,
        cost_trend=cost_trend,
    )


# ── SVG sparkline for cost trend ────────────────────────────────────


def render_cost_sparkline_svg(
    points: list[LotPricePoint],
    *,
    width: int = 360,
    height: int = 90,
    color: str = "#0d6efd",
) -> str:
    """Render a tiny inline SVG line chart of unit price over time.

    Mirrors the style of template_stats.render_sparkline_svg but works
    on LotPricePoint values. Returns "" if fewer than 2 priced points.
    """
    priced = [p for p in points if p.unit_price is not None]
    if len(priced) < 2:
        return ""

    ys = [p.unit_price for p in priced]
    xs = list(range(len(priced)))

    pad = 14
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    x_min, x_max = 0, len(priced) - 1
    y_min, y_max = min(ys), max(ys)
    if x_max == x_min:
        x_max = x_min + 1
    y_range = y_max - y_min

    if y_range == 0:
        coords = [(pad + (i - x_min) / (x_max - x_min) * inner_w, pad + inner_h / 2) for i in xs]
    else:
        coords = [
            (
                pad + (i - x_min) / (x_max - x_min) * inner_w,
                pad + inner_h - (v - y_min) / y_range * inner_h,
            )
            for i, v in zip(xs, ys, strict=True)
        ]

    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"/>' for x, y in coords)

    first_x, first_y = coords[0]
    last_x, last_y = coords[-1]
    first_v, last_v = ys[0], ys[-1]

    def _fmt(v: float) -> str:
        return f"{v:.3f}" if v < 1 else f"{v:.2f}"

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'style="display:block;max-width:100%;height:auto" '
        f'aria-label="cost trend">'
        f'<path d="{path_d}" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        f"{dots}"
        f'<text x="{first_x:.1f}" y="{first_y - 6:.1f}" '
        f'font-size="9" fill="#888" text-anchor="start">{_fmt(first_v)}</text>'
        f'<text x="{last_x:.1f}" y="{last_y - 6:.1f}" '
        f'font-size="9" fill="#222" font-weight="bold" '
        f'text-anchor="end">{_fmt(last_v)}</text>'
        f"</svg>"
    )
