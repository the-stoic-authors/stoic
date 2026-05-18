"""Stoic ELN — Run cost calculator (Settimana 6 patch 5).

Computes the materials cost of a run from the actual quantities
consumed and the per-unit cost of the inventory lots they were drawn
from.

Definition: "the cost of a run is what came out of your lots,
computed on actual quantities consumed."

Includes both:
  - main reaction components (RunComponent)
  - workup/extraction step components (RunStepComponent)

Includes solvents (DCM in a coupling can be the dominant cost).
Excludes products (they don't deduct from inventory; rather, runs
*create* product lots).

When a component:
  - has no ``inventory_item_id``: cost is None (it was not deducted
    from a real lot — likely a forgotten lot assignment)
  - has a lot but no ``actual_*`` quantity: cost is None (run not
    started yet, or quantity not entered)
  - has both but the lot has ``total_cost_eur=NULL``: cost is None
    (lot's price wasn't entered when it was added to inventory)

The total cost of the run is the sum of all line costs that are
non-None — None lines contribute 0 but are surfaced in the breakdown
so the user knows there are gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stoic_eln.models.run import Run


@dataclass
class CostLine:
    """One line in the cost breakdown."""

    source: str          # "main" | "step"
    step_title: str | None  # only for "step" lines
    substance_name: str
    role: str            # 'starting_material', 'reactant', 'solvent', etc.
    actual_quantity_display: str    # "0.785 g" or "25.0 mL" or "—"
    has_lot: bool        # whether inventory_item_id is set
    has_cost_data: bool  # whether the lot has a total_cost_eur and unit cost
    cost_eur: float | None  # the line cost; None if data missing
    is_from_internal_lot: bool  # True if the lot was produced by another run

    @property
    def is_complete(self) -> bool:
        return self.cost_eur is not None


@dataclass
class RunCostBreakdown:
    """Full cost breakdown for one run.

    Two views of the total:
      - ``total_eur`` (cumulative) — everything consumed, including the
        full cost of any intermediate lots (those produced by previous
        runs). This is the *real* what-it-cost-me-to-make-this number.
      - ``direct_total_eur`` — only the cost of "freshly purchased"
        materials consumed in this run, i.e. lots NOT produced by a
        previous run. This is what hit your purchase budget directly.

    The difference (cumulative − direct) is the value of intermediates
    consumed (= ``intermediates_total_eur``). Useful when you want to
    know "how much did THIS step alone add" vs "how much did the
    overall synthesis cost so far".
    """

    lines: list[CostLine]
    total_eur: float                    # CUMULATIVE — everything
    direct_total_eur: float             # only externally-purchased
    intermediates_total_eur: float      # cumulative − direct
    incomplete_count: int
    is_product_priced: bool

    @property
    def has_data(self) -> bool:
        return any(l.is_complete for l in self.lines)

    @property
    def main_total_eur(self) -> float:
        return sum(l.cost_eur or 0.0 for l in self.lines if l.source == "main")

    @property
    def steps_total_eur(self) -> float:
        return sum(l.cost_eur or 0.0 for l in self.lines if l.source == "step")


# ─── Helpers ────────────────────────────────────────────────────────


def _line_cost(actual_g: float | None,
               actual_mL: float | None,
               lot) -> float | None:
    """Return the line cost in EUR, or None if data missing.

    Uses the lot's ``cost_per_unit`` (€/g or €/mL based on the lot's
    initial-quantity unit) and matches it against the actual unit
    used. If they don't match (e.g. lot is sold in g but the run
    consumed mL), we fall back to None — the user can fix the data.
    """
    if lot is None:
        return None
    cpu = lot.cost_per_unit  # €/g or €/mL
    if cpu is None:
        return None
    unit = lot.cost_per_unit_unit  # "/g" or "/mL"
    if unit == "/g" and actual_g is not None and actual_g > 0:
        return cpu * actual_g
    if unit == "/mL" and actual_mL is not None and actual_mL > 0:
        return cpu * actual_mL
    return None


def _qty_display(g: float | None, mL: float | None) -> str:
    if g is not None and g > 0:
        return f"{g:g} g"
    if mL is not None and mL > 0:
        return f"{mL:g} mL"
    return "—"


# ─── Public API ─────────────────────────────────────────────────────


# Roles that are PRODUCED, not consumed — exclude from cost.
PRODUCED_ROLES = ("product", "byproduct")


def compute_run_cost(run: "Run") -> RunCostBreakdown:
    """Compute the total materials cost of ``run``.

    Walks both ``run.components`` and ``run.steps[*].components``,
    builds a CostLine per consumed component, and computes both the
    cumulative total (everything) and the direct total (excluding
    cost of lots that were produced by previous runs — so you can
    see how much fresh-money this step consumed).
    """
    lines: list[CostLine] = []
    incomplete = 0

    # Main reaction components
    for c in sorted(run.components, key=lambda x: x.position):
        if c.role in PRODUCED_ROLES:
            continue
        sub = c.substance
        lot = c.inventory_item
        cost = _line_cost(c.actual_mass_g, c.actual_volume_mL, lot)
        is_internal = bool(lot and lot.source_run_id is not None)
        line = CostLine(
            source="main",
            step_title=None,
            substance_name=sub.name if sub else "?",
            role=c.role,
            actual_quantity_display=_qty_display(c.actual_mass_g,
                                                  c.actual_volume_mL),
            has_lot=lot is not None,
            has_cost_data=lot is not None and lot.cost_per_unit is not None,
            cost_eur=cost,
            is_from_internal_lot=is_internal,
        )
        if cost is None:
            incomplete += 1
        lines.append(line)

    # Step components (workup, extraction, ...)
    for step in sorted(run.steps, key=lambda x: x.position):
        for sc in sorted(step.components, key=lambda x: x.position):
            if sc.role in PRODUCED_ROLES:
                continue
            sub = sc.substance
            lot = sc.inventory_item
            cost = _line_cost(sc.actual_mass_g, sc.actual_volume_mL, lot)
            is_internal = bool(lot and lot.source_run_id is not None)
            line = CostLine(
                source="step",
                step_title=step.title,
                substance_name=sub.name if sub else "?",
                role=sc.role,
                actual_quantity_display=_qty_display(sc.actual_mass_g,
                                                      sc.actual_volume_mL),
                has_lot=lot is not None,
                has_cost_data=lot is not None and lot.cost_per_unit is not None,
                cost_eur=cost,
                is_from_internal_lot=is_internal,
            )
            if cost is None:
                incomplete += 1
            lines.append(line)

    cumulative = sum(l.cost_eur or 0.0 for l in lines)
    direct = sum(
        (l.cost_eur or 0.0) for l in lines
        if not l.is_from_internal_lot
    )
    intermediates = cumulative - direct

    has_yield = (run.yield_g is not None and run.yield_g > 0)

    return RunCostBreakdown(
        lines=lines,
        total_eur=cumulative,
        direct_total_eur=direct,
        intermediates_total_eur=intermediates,
        incomplete_count=incomplete,
        is_product_priced=has_yield and cumulative > 0,
    )


def compute_run_cost_cumulative(run: "Run",
                                  breakdown: RunCostBreakdown | None = None) -> float:
    """Convenience wrapper: returns the cumulative cost only.

    Used by ``complete_run`` to allocate cost to product lots.
    """
    bd = breakdown if breakdown is not None else compute_run_cost(run)
    return bd.total_eur


@dataclass
class CostMetrics:
    """Per-unit cost of the product, computed for one cost basis.

    Each field is None if not derivable (missing yield, MW, density).
    """
    per_mol: float | None
    per_g: float | None
    per_mL: float | None
    basis_eur: float          # the total cost this metric was derived from


def product_unit_metrics(run: "Run", basis_eur: float) -> CostMetrics:
    """Express ``basis_eur`` as €/mol, €/g, and €/mL of product.

    The basis is typically ``breakdown.total_eur`` (cumulative) or
    ``breakdown.direct_total_eur`` (direct). Caller picks.
    """
    empty = CostMetrics(per_mol=None, per_g=None, per_mL=None,
                        basis_eur=basis_eur)
    if basis_eur <= 0:
        return empty
    if not run.yield_g or run.yield_g <= 0:
        return empty

    # Find the product component to access the substance
    product = None
    for c in run.components:
        if c.role == "product":
            product = c
            break
    if product is None or product.substance is None:
        return empty

    sub = product.substance
    yield_g = run.yield_g

    # €/g — always available when yield_g > 0
    per_g = basis_eur / yield_g

    # €/mol — needs MW
    per_mol = None
    if sub.molecular_weight and sub.molecular_weight > 0:
        moles = yield_g / sub.molecular_weight
        if moles > 0:
            per_mol = basis_eur / moles

    # €/mL — only if the product has a density (liquid product)
    per_mL = None
    density = getattr(sub, "density", None)
    if density and density > 0:
        volume_mL = yield_g / density
        if volume_mL > 0:
            per_mL = basis_eur / volume_mL

    return CostMetrics(per_mol=per_mol, per_g=per_g, per_mL=per_mL,
                       basis_eur=basis_eur)


def cost_per_mol_product(run: "Run", breakdown: RunCostBreakdown) -> float | None:
    """Backwards-compat wrapper: € per mole on the cumulative basis."""
    if not breakdown.is_product_priced:
        return None
    return product_unit_metrics(run, breakdown.total_eur).per_mol
