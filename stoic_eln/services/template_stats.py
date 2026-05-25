"""Stoic ELN — Statistiche aggregate per template (Settimana 6 patch 6).

For each reaction template (identified by ``template_code_base`` so all
versions of "SUZ" — SUZ.1, SUZ.2, ... — are aggregated together),
compute aggregate metrics over its completed runs:

  - number of runs
  - average / min / max cumulative cost €
  - average / min / max €/g of product (cumulative)
  - average yield %
  - last run (most recent), with its individual cost
  - a series of (run_code, date, cost_eur, cost_per_g, yield_percent)
    points for charting

Why ``template_code_base``? Because a template like SUZ.1 may evolve
into SUZ.2 (a published successor with the same logical procedure
but updated parameters) — we want stats grouped by the procedure,
not by the specific version. The ``Reaction`` model already exposes
``template_code_base`` as a column.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_

from stoic_eln.extensions import db
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.run import Run, STATUS_COMPLETED
from stoic_eln.services.run_cost import compute_run_cost, product_unit_metrics

if TYPE_CHECKING:
    pass


@dataclass
class RunPoint:
    """One data point per completed run, used for tables and charts."""

    run_id: int
    run_code: str
    completed_at: datetime | None
    cost_eur: float  # cumulative
    cost_per_g: float | None  # cumulative €/g of product
    yield_percent: float | None
    yield_g: float | None
    operator_name: str | None


@dataclass
class TemplateStats:
    """Aggregate cost/yield stats over the completed runs of one template."""

    template_code_base: str
    template_title: str | None  # latest title (most recent reaction's)
    n_runs: int
    n_runs_with_cost: int  # subset that have non-zero cost data

    avg_cost_eur: float | None
    min_cost_eur: float | None
    max_cost_eur: float | None

    avg_cost_per_g: float | None
    min_cost_per_g: float | None
    max_cost_per_g: float | None

    avg_yield_percent: float | None
    last_run: RunPoint | None  # most recent
    points: list[RunPoint] = field(default_factory=list)  # chronological

    @property
    def has_data(self) -> bool:
        return self.n_runs > 0


def _operator_name(run: Run) -> str | None:
    if run.operator is None:
        return None
    return run.operator.full_name or run.operator.username


def _build_run_point(run: Run) -> RunPoint:
    """Compute the metric bundle for a single completed run."""
    bd = compute_run_cost(run)
    metrics = product_unit_metrics(run, bd.total_eur)
    return RunPoint(
        run_id=run.id,
        run_code=run.code,
        completed_at=run.completed_at,
        cost_eur=bd.total_eur,
        cost_per_g=metrics.per_g,
        yield_percent=run.yield_percent,
        yield_g=run.yield_g,
        operator_name=_operator_name(run),
    )


def stats_for_template(template_code_base: str) -> TemplateStats:
    """Stats over all completed runs of a template family (all versions)."""
    # Find every run whose Reaction.template_code_base matches.
    runs = (
        db.session.query(Run)
        .join(Reaction, Run.reaction_id == Reaction.id)
        .filter(
            and_(
                Run.status == STATUS_COMPLETED,
                Reaction.template_code_base == template_code_base,
            )
        )
        .order_by(Run.completed_at.asc().nulls_last(), Run.created_at.asc())
        .all()
    )

    points = [_build_run_point(r) for r in runs]
    points_with_cost = [p for p in points if p.cost_eur > 0]

    # Latest reaction's title (within this template_code_base) for display
    latest_rxn = (
        db.session.query(Reaction)
        .filter(Reaction.template_code_base == template_code_base)
        .order_by(Reaction.version_number.desc())
        .first()
    )

    def _avg(vals):
        return (sum(vals) / len(vals)) if vals else None

    def _min(vals):
        return min(vals) if vals else None

    def _max(vals):
        return max(vals) if vals else None

    costs = [p.cost_eur for p in points_with_cost]
    cpgs = [p.cost_per_g for p in points_with_cost if p.cost_per_g is not None]
    ys = [p.yield_percent for p in points if p.yield_percent is not None]

    return TemplateStats(
        template_code_base=template_code_base,
        template_title=(latest_rxn.title if latest_rxn else None),
        n_runs=len(points),
        n_runs_with_cost=len(points_with_cost),
        avg_cost_eur=_avg(costs),
        min_cost_eur=_min(costs),
        max_cost_eur=_max(costs),
        avg_cost_per_g=_avg(cpgs),
        min_cost_per_g=_min(cpgs),
        max_cost_per_g=_max(cpgs),
        avg_yield_percent=_avg(ys),
        last_run=(points[-1] if points else None),
        points=points,
    )


def all_templates_stats() -> list[TemplateStats]:
    """Stats for EVERY template that has at least one completed run.

    Sorted by n_runs DESC then by last_run desc.
    """
    bases = (
        db.session.query(Reaction.template_code_base)
        .join(Run, Run.reaction_id == Reaction.id)
        .filter(Run.status == STATUS_COMPLETED)
        .distinct()
        .all()
    )
    bases = [b[0] for b in bases if b[0]]

    out = [stats_for_template(b) for b in bases]
    out.sort(
        key=lambda s: (
            -s.n_runs,
            -(s.last_run.completed_at.timestamp() if s.last_run and s.last_run.completed_at else 0),
        )
    )
    return out


# ── SVG sparkline rendering ─────────────────────────────────────────


def render_sparkline_svg(
    points: list[RunPoint],
    *,
    metric: str = "cost_per_g",  # 'cost_per_g' | 'cost_eur' | 'yield_percent'
    width: int = 320,
    height: int = 80,
    color: str = "#0d6efd",
) -> str:
    """Render a tiny inline SVG line chart.

    Returns an empty string if there's not enough data.

    The SVG is intentionally minimal: no axes, no grid, just the line
    plus dots at each point and a label for first and last value.
    """
    # Pull values
    if metric == "cost_per_g":
        values = [p.cost_per_g for p in points]
    elif metric == "cost_eur":
        values = [p.cost_eur for p in points]
    elif metric == "yield_percent":
        values = [p.yield_percent for p in points]
    else:
        return ""

    # Need at least 2 valid points
    pairs = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pairs) < 2:
        return ""

    xs = [i for i, _ in pairs]
    ys = [v for _, v in pairs]

    pad = 12
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_max == x_min:
        x_max = x_min + 1
    y_range = y_max - y_min
    if y_range == 0:
        # Flat line — show at midline
        coords = [(pad + (i - x_min) / (x_max - x_min) * inner_w, pad + inner_h / 2) for i in xs]
    else:
        coords = [
            (
                pad + (i - x_min) / (x_max - x_min) * inner_w,
                pad + inner_h - (v - y_min) / y_range * inner_h,
            )
            for i, v in pairs
        ]

    # Polyline path
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in coords)

    # Dots on each point
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"/>' for x, y in coords)

    # Labels for first and last value
    first_x, first_y = coords[0]
    last_x, last_y = coords[-1]
    first_v, last_v = ys[0], ys[-1]
    fmt = (lambda v: f"{v:.1f}") if y_max < 100 else (lambda v: f"{v:.0f}")

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'style="display:block;max-width:100%;height:auto" '
        f'aria-label="trend">'
        f'<path d="{path_d}" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        f"{dots}"
        f'<text x="{first_x:.1f}" y="{first_y - 6:.1f}" '
        f'font-size="9" fill="#888" text-anchor="start">{fmt(first_v)}</text>'
        f'<text x="{last_x:.1f}" y="{last_y - 6:.1f}" '
        f'font-size="9" fill="#222" font-weight="bold" '
        f'text-anchor="end">{fmt(last_v)}</text>'
        f"</svg>"
    )
    return svg
