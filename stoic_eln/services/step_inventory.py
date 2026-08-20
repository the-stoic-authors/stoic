"""Stoic ELN — incremental inventory deduction for step components (v1.4.4).

Why this exists
---------------
Main reaction components are declared *before* the run starts: you type
the masses you are about to weigh, press Avvia, and ``start_run()``
deducts them all at once. After that the route refuses further edits, so
one deduction per component is enough.

Step components (workup, extraction, chromatography) don't work that
way. You cannot know in advance how much DCM the column will take, so
``set_step_actual`` deliberately accepts edits both in ``draft`` and in
``in_progress``. Until v1.4.4 those quantities were counted by
``run_cost`` but never removed from the lot: the solvent had a price but
no consumption.

The fix is incremental. Each step component remembers how much it has
already taken and from which lot (``deducted_*`` columns). On every
change we compute the difference and move only that:

    declared 50 mL, already taken 0   → take 50
    corrected to 40 mL, already 50    → give 10 back
    lot swapped                       → give all back to the old lot,
                                        take the full amount from the new
    field cleared                     → give everything back

Rules of engagement
-------------------
- **Draft never deducts.** In draft you are planning, exactly like the
  main components which only move stock at Avvia. Deduction starts at
  ``start_run()`` (which syncs any step quantity already filled in) and
  stays live for the whole ``in_progress`` phase.
- **Never block, always record.** A step quantity is a fact that already
  happened at the bench — refusing to record it would be wrong. If the
  lot doesn't hold enough, we take it down to zero and report the
  shortfall as a warning, so the discrepancy surfaces instead of hiding.
- **No lot, no deduction.** A component with no lot bound (or a free
  entry) is simply not tracked; ``run_cost`` already treats that as a
  known gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stoic_eln.models.inventory import InventoryItem
    from stoic_eln.models.run import Run
    from stoic_eln.models.run_step import RunStepComponent


# Quantities are floats coming from user input; treat anything below
# this as zero so rounding noise never creates 1e-16 deductions.
_EPS = 1e-9


@dataclass
class StepDeduction:
    """What one sync actually moved, for the caller to report."""

    component_name: str
    lot_label: str | None
    unit: str | None
    deducted: float = 0.0
    returned: float = 0.0
    shortfall: float = 0.0

    @property
    def has_shortfall(self) -> bool:
        return self.shortfall > _EPS


# ── Small helpers on the two parallel quantity channels ─────────────


def _declared(sc: RunStepComponent) -> tuple[float | None, str | None]:
    """The quantity the operator says was used, and its unit."""
    if sc.actual_mass_g is not None:
        return sc.actual_mass_g, "g"
    if sc.actual_volume_mL is not None:
        return sc.actual_volume_mL, "mL"
    return None, None


def _already_taken(sc: RunStepComponent) -> tuple[float | None, str | None]:
    """The quantity this component has already removed from its lot."""
    if sc.deducted_mass_g is not None:
        return sc.deducted_mass_g, "g"
    if sc.deducted_volume_mL is not None:
        return sc.deducted_volume_mL, "mL"
    return None, None


def _remember(
    sc: RunStepComponent,
    amount: float | None,
    unit: str | None,
    lot_id: int | None,
) -> None:
    """Record what is currently held from the lot (or clear it)."""
    if amount is None or amount <= _EPS or unit is None or lot_id is None:
        sc.deducted_mass_g = None
        sc.deducted_volume_mL = None
        sc.deducted_lot_id = None
        return
    sc.deducted_mass_g = amount if unit == "g" else None
    sc.deducted_volume_mL = amount if unit == "mL" else None
    sc.deducted_lot_id = lot_id


def _give_back(lot: InventoryItem | None, amount: float, unit: str | None) -> None:
    """Return ``amount`` to the lot. A lot whose channel was NULL is
    treated as zero — giving back can legitimately push it above the
    initial quantity only if it was over-deducted, never otherwise."""
    if lot is None or unit is None or amount <= _EPS:
        return
    if unit == "g":
        lot.quantity_g = (lot.quantity_g or 0.0) + amount
    elif unit == "mL":
        lot.quantity_mL = (lot.quantity_mL or 0.0) + amount


def _take(lot: InventoryItem | None, amount: float, unit: str | None) -> tuple[float, float]:
    """Remove up to ``amount`` from the lot.

    Returns ``(taken, shortfall)``. The lot is clamped at zero rather
    than going negative: a lot that reads 0 with a logged shortfall is
    honest, a negative lot is just broken data.
    """
    if lot is None or unit is None or amount <= _EPS:
        return 0.0, 0.0
    available = (lot.quantity_g if unit == "g" else lot.quantity_mL) or 0.0
    taken = min(amount, available)
    if unit == "g":
        lot.quantity_g = available - taken
    else:
        lot.quantity_mL = available - taken
    return taken, amount - taken


def _lot_label(lot: InventoryItem | None) -> str | None:
    if lot is None:
        return None
    return lot.batch_code or f"#{lot.id}"


# ── The sync itself ─────────────────────────────────────────────────


def sync_step_component(sc: RunStepComponent, *, active: bool) -> StepDeduction | None:
    """Reconcile one step component's lot with its declared quantity.

    ``active`` is True while the run is in progress. When False (draft,
    or a run that never started) nothing is held: any previous deduction
    is returned to its lot.

    Returns None when nothing moved, so callers can stay quiet in the
    common case.
    """
    from stoic_eln.extensions import db
    from stoic_eln.models.inventory import InventoryItem

    want_amount, want_unit = _declared(sc) if active else (None, None)
    want_lot_id = sc.inventory_item_id if active else None
    if want_amount is None or want_amount <= _EPS or want_lot_id is None:
        want_amount, want_unit, want_lot_id = None, None, None

    held_amount, held_unit = _already_taken(sc)
    held_lot_id = sc.deducted_lot_id

    if held_lot_id is None and want_lot_id is None:
        # Nothing held, nothing wanted: make sure the bookkeeping is clean.
        _remember(sc, None, None, None)
        return None

    held_lot = db.session.get(InventoryItem, held_lot_id) if held_lot_id else None
    want_lot = db.session.get(InventoryItem, want_lot_id) if want_lot_id else None

    deducted = returned = shortfall = 0.0
    same_target = held_lot_id is not None and held_lot_id == want_lot_id and held_unit == want_unit

    if same_target:
        delta = (want_amount or 0.0) - (held_amount or 0.0)
        if delta > _EPS:
            deducted, shortfall = _take(want_lot, delta, want_unit)
            _remember(sc, (held_amount or 0.0) + deducted, want_unit, want_lot_id)
        elif delta < -_EPS:
            returned = -delta
            _give_back(held_lot, returned, held_unit)
            _remember(sc, want_amount, want_unit, want_lot_id)
        else:
            return None
    else:
        # Different lot, different unit, or one side empty: unwind the
        # old position completely before opening the new one.
        if held_amount and held_lot is not None:
            returned = held_amount
            _give_back(held_lot, returned, held_unit)
        _remember(sc, None, None, None)
        if want_amount and want_lot is not None:
            deducted, shortfall = _take(want_lot, want_amount, want_unit)
            _remember(sc, deducted, want_unit, want_lot_id)

    if deducted <= _EPS and returned <= _EPS and shortfall <= _EPS:
        return None

    return StepDeduction(
        component_name=sc.display_name
        if (sc.substance_id or sc.mixture_id)
        else (sc.free_name or "—"),
        lot_label=_lot_label(want_lot or held_lot),
        unit=want_unit or held_unit,
        deducted=deducted,
        returned=returned,
        shortfall=shortfall,
    )


def sync_run_step_inventory(run: Run) -> list[StepDeduction]:
    """Reconcile every step component of ``run`` in one pass.

    Used by ``start_run()`` to pick up quantities that were already
    filled in during draft, and available to any caller that needs to
    re-settle a whole run.
    """
    from stoic_eln.models.run import STATUS_IN_PROGRESS

    active = run.status == STATUS_IN_PROGRESS
    results: list[StepDeduction] = []
    for step in run.steps:
        for sc in step.components:
            res = sync_step_component(sc, active=active)
            if res is not None:
                results.append(res)
    return results
