"""Stoic ELN — Production-cost report.

What did it cost to *make* each in-house batch, and each substance overall?

A produced batch is an ``InventoryItem`` with ``source_run_id`` set (created
by ``complete_run``). Its production cost is the cost of the materials its
run consumed — which ``run_cost.compute_run_cost`` already computes on two
bases:

  * **cumulative** — every material consumed, including the embedded cost of
    self-made intermediates used in the run (full cost accounting).
  * **direct** — fresh purchased money only, excluding intermediates already
    paid for in earlier runs (cash cost).

When a run yields several products, its run-level cost is split across the
product batches **in proportion to mass** (the same allocation
``complete_run`` uses), so €/g is uniform across a run's products.

This module aggregates that per batch and per substance over a period.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func

from stoic_eln.extensions import db
from stoic_eln.models import InventoryItem, Run, Substance
from stoic_eln.services.run_cost import compute_run_cost


# ── Data structures ─────────────────────────────────────────────────


@dataclass
class ProductionBatchRow:
    batch_code: str | None
    run_code: str | None
    run_id: int | None
    produced_g: float | None
    produced_on: date | None
    cost_cumulative: float | None
    cost_direct: float | None
    per_g_cumulative: float | None
    per_g_direct: float | None
    partial: bool  # the run had components with no price → costs understated


@dataclass
class ProductionSubstanceSummary:
    substance_id: int
    substance_name: str
    batch_count: int = 0
    total_produced_g: float = 0.0
    total_cost_cumulative: float = 0.0
    total_cost_direct: float = 0.0
    any_partial: bool = False
    batches: list[ProductionBatchRow] = field(default_factory=list)

    @property
    def avg_per_g_cumulative(self) -> float | None:
        return self.total_cost_cumulative / self.total_produced_g if self.total_produced_g else None

    @property
    def avg_per_g_direct(self) -> float | None:
        return self.total_cost_direct / self.total_produced_g if self.total_produced_g else None


@dataclass
class ProductionCostReport:
    date_from: date | None
    date_to: date | None
    substances: list[ProductionSubstanceSummary] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.substances)

    @property
    def total_cost_cumulative(self) -> float:
        return sum(s.total_cost_cumulative for s in self.substances)

    @property
    def total_cost_direct(self) -> float:
        return sum(s.total_cost_direct for s in self.substances)

    @property
    def total_produced_g(self) -> float:
        return sum(s.total_produced_g for s in self.substances)


# ── Computation ─────────────────────────────────────────────────────


def _as_date(d: datetime | date | None) -> date | None:
    if isinstance(d, datetime):
        return d.date()
    return d


def compute_production_cost_report(
    date_from: date | None = None,
    date_to: date | None = None,
) -> ProductionCostReport:
    """Aggregate production cost per substance and per produced batch.

    Batches are filtered by their production date (the source run's
    ``completed_at``, falling back to the batch ``created_at``).
    """
    # Produced, substance-backed batches with a real mass.
    q = db.session.query(InventoryItem).filter(
        InventoryItem.source_run_id.isnot(None),
        InventoryItem.substance_id.isnot(None),
        InventoryItem.initial_quantity_g.isnot(None),
        InventoryItem.initial_quantity_g > 0,
    )
    batches = q.all()
    if not batches:
        return ProductionCostReport(date_from=date_from, date_to=date_to)

    run_ids = {b.source_run_id for b in batches}
    runs = {r.id: r for r in db.session.query(Run).filter(Run.id.in_(run_ids)).all()}

    # Total produced mass per run (denominator for mass allocation) —
    # over ALL of a run's product batches, so shares sum to 1.
    run_total_mass: dict[int, float] = dict(
        db.session.query(
            InventoryItem.source_run_id,
            func.sum(InventoryItem.initial_quantity_g),
        )
        .filter(
            InventoryItem.source_run_id.in_(run_ids),
            InventoryItem.initial_quantity_g.isnot(None),
        )
        .group_by(InventoryItem.source_run_id)
        .all()
    )

    # One cost breakdown per run.
    breakdowns = {rid: compute_run_cost(runs[rid]) for rid in run_ids if rid in runs}

    summaries: dict[int, ProductionSubstanceSummary] = {}

    for b in batches:
        run = runs.get(b.source_run_id)
        bd = breakdowns.get(b.source_run_id)
        produced_on = _as_date(run.completed_at if run else None) or _as_date(b.created_at)

        # Period filter on production date
        if date_from and produced_on and produced_on < date_from:
            continue
        if date_to and produced_on and produced_on > date_to:
            continue

        mass = b.initial_quantity_g or 0.0
        total_mass = run_total_mass.get(b.source_run_id, 0.0) or 0.0
        share = (mass / total_mass) if total_mass > 0 else 0.0

        cost_cum = bd.total_eur * share if bd else None
        cost_dir = bd.direct_total_eur * share if bd else None
        per_g_cum = (cost_cum / mass) if (cost_cum is not None and mass) else None
        per_g_dir = (cost_dir / mass) if (cost_dir is not None and mass) else None
        partial = bool(bd and bd.incomplete_count > 0)

        row = ProductionBatchRow(
            batch_code=b.batch_code,
            run_code=run.code if run else None,
            run_id=b.source_run_id,
            produced_g=mass,
            produced_on=produced_on,
            cost_cumulative=cost_cum,
            cost_direct=cost_dir,
            per_g_cumulative=per_g_cum,
            per_g_direct=per_g_dir,
            partial=partial,
        )

        sid = b.substance_id
        summ = summaries.get(sid)
        if summ is None:
            sub = db.session.get(Substance, sid)
            summ = ProductionSubstanceSummary(
                substance_id=sid,
                substance_name=sub.name if sub else f"#{sid}",
            )
            summaries[sid] = summ
        summ.batch_count += 1
        summ.total_produced_g += mass
        summ.total_cost_cumulative += cost_cum or 0.0
        summ.total_cost_direct += cost_dir or 0.0
        summ.any_partial = summ.any_partial or partial
        summ.batches.append(row)

    # Sort batches newest-first within a substance; substances by cumulative cost desc.
    for summ in summaries.values():
        summ.batches.sort(key=lambda r: r.produced_on or date.min, reverse=True)

    ordered = sorted(
        summaries.values(),
        key=lambda s: s.total_cost_cumulative,
        reverse=True,
    )
    return ProductionCostReport(date_from=date_from, date_to=date_to, substances=ordered)
