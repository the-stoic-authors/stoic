"""Backfill production cost on mixture lots.

A prepared mixture is an ``InventoryItem`` (``mixture_id`` set) created by a
``MixturePrep``. Lots prepared *before* the prep-costing fix have
``total_cost_eur = None``, so runs that consume them can't count their cost.

This recomputes each such lot's cost from its recorded consumptions — the sum
of the **priced** precursor lines (an unpriced precursor is skipped; the cost
is set as long as at least one precursor was priced). It reuses the model's own
``MixturePrepConsumption.imputed_cost_eur`` so it matches the live prep logic.

Chained preps (a mixture made from another mixture) are handled by repeating
passes until no further lot can be priced.

This lives in ``services`` (not ``scripts``) so it is importable from the
installed package on any machine — tests import it directly. The CLI wrapper in
``scripts/backfill_mixture_costs.py`` handles argument parsing and app setup.
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.mixture_prep import MixturePrep


def _partial_cost(prep) -> tuple[float | None, int, int]:
    """(cost, n_priced, n_total) — sum of the priced consumptions, or
    (None, 0, n) when no consumption is priced yet."""
    pieces = [c.imputed_cost_eur for c in prep.consumptions]
    priced = [p for p in pieces if p is not None]
    if not priced:
        return None, 0, len(pieces)
    return sum(priced), len(priced), len(pieces)


def run_backfill(apply: bool) -> dict:
    """Price mixture lots that have no cost from their prep consumptions.

    Values are set in the session first (so chained preps see upstream
    prices on later passes); the transaction is committed only when
    ``apply`` is True, otherwise rolled back. Returns a summary dict.
    """
    lots = (
        db.session.query(InventoryItem)
        .filter(
            InventoryItem.mixture_id.isnot(None),
            InventoryItem.total_cost_eur.is_(None),
        )
        .all()
    )

    prep_by_lot: dict[int, MixturePrep] = {}
    for lot in lots:
        prep = (
            db.session.query(MixturePrep)
            .filter(MixturePrep.output_inventory_item_id == lot.id)
            .first()
        )
        if prep is not None:
            prep_by_lot[lot.id] = prep

    no_prep = [lot for lot in lots if lot.id not in prep_by_lot]
    pending = {lot.id: lot for lot in lots if lot.id in prep_by_lot}
    priced: list[tuple] = []

    # Repeat passes: a mixture built from another mixture can only be
    # priced once its precursor lot has been priced.
    changed = True
    while changed and pending:
        changed = False
        for lot_id in list(pending):
            cost, n_priced, n_total = _partial_cost(prep_by_lot[lot_id])
            if cost is None:
                continue
            lot = pending.pop(lot_id)
            lot.total_cost_eur = cost
            db.session.flush()  # so dependent lots' imputed cost sees this
            priced.append((lot, cost, n_priced, n_total))
            changed = True

    summary = {
        "priced": priced,
        "no_prep": no_prep,
        "unpriced": list(pending.values()),  # prep present, no priced precursor
        "applied": apply,
    }
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return summary
