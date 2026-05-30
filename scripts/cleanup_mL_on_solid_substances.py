"""Stoic ELN — Cleanup: undo over-eager mL propagation on solid substances.

A previous migration (``migrate_inventory_quantity_policy.py``) assumed
that any substance with a non-null ``density`` field was volume-dosable
and propagated the missing unit accordingly. That was wrong for solid
crystalline substances whose density is the crystal density of the
powder, not a usable "volume of a syringe-able liquid" — e.g. sodium
sulphate has density 2.66 g/cm³ and melting point 884°C.

This script complements the v0.10.1 policy patch which added a
physical-state check (MP > 25°C → treat as solid, ignore density for
unit policy). It walks every active substance-backed InventoryItem,
re-evaluates the policy, and for lots whose substance is now classified
as "reagent_no_density" but still carry a ``quantity_mL`` value:

  - if ``quantity_g`` is also set: clear ``quantity_mL`` (and
    ``initial_quantity_mL`` if also set); the gram value is the truth.
  - if only ``quantity_mL`` is set: convert it back to grams via the
    catalog density (best we can do — the original mass was wherever
    the operator entered it) and clear mL.

Idempotent and safe to re-run. Does not touch substance-with-low-MP
lots (the matrix still allows mL there) nor mixture lots (out of scope).

Usage:
    cd ~/Projects/stoic-eln
    .venv/bin/python -m scripts.cleanup_mL_on_solid_substances
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models import InventoryItem
from stoic_eln.services.inventory_quantity import policy_for_substance


def main() -> dict:
    summary = {
        "scanned": 0,
        "skipped_mixture": 0,
        "skipped_no_substance": 0,
        "skipped_dosable_in_volume": 0,
        "cleared_mL_only": 0,
        "converted_mL_to_g": 0,
        "already_clean": 0,
        "touched_items": [],  # (id, batch_code, action)
    }

    items = db.session.query(InventoryItem).filter(InventoryItem.is_active.is_(True)).all()

    for it in items:
        summary["scanned"] += 1

        if it.mixture_id is not None:
            summary["skipped_mixture"] += 1
            continue

        sub = it.substance
        if sub is None:
            summary["skipped_no_substance"] += 1
            continue

        new_policy = policy_for_substance(sub)

        # If the substance is still allowed in mL under the new policy,
        # no cleanup needed (it's either a real liquid, or the operator
        # explicitly flagged it as solvent).
        if new_policy.allow_mL:
            summary["skipped_dosable_in_volume"] += 1
            continue

        # The new policy says: this is a solid, only g. Clear any mL.
        has_init_mL = it.initial_quantity_mL is not None
        has_rem_mL = it.quantity_mL is not None
        if not has_init_mL and not has_rem_mL:
            summary["already_clean"] += 1
            continue

        # If g is missing but mL is set, recover g from mL using the
        # density that's on the substance record (even if we now
        # consider it "solid for policy purposes", the density value
        # is still the best info we have to reconstruct mass).
        density = getattr(sub, "density", None)
        action = None

        if has_rem_mL and it.quantity_g is None and density and density > 0:
            it.quantity_g = round(it.quantity_mL * density, 6)
            action = "converted"
        if has_init_mL and it.initial_quantity_g is None and density and density > 0:
            it.initial_quantity_g = round(it.initial_quantity_mL * density, 6)
            action = "converted"

        it.initial_quantity_mL = None
        it.quantity_mL = None

        if action == "converted":
            summary["converted_mL_to_g"] += 1
        else:
            summary["cleared_mL_only"] += 1

        summary["touched_items"].append((it.id, it.batch_code, sub.name, action or "cleared_mL"))

    db.session.commit()
    return summary


def print_summary(summary: dict) -> None:
    print("=" * 64)
    print("Cleanup: undo mL propagation on solid substances")
    print("=" * 64)
    print(f"Scanned active lots:                   {summary['scanned']}")
    print(f"Skipped (mixture lot):                 {summary['skipped_mixture']}")
    print(f"Skipped (no substance):                {summary['skipped_no_substance']}")
    print(f"Skipped (still dosable in volume):     {summary['skipped_dosable_in_volume']}")
    print(f"Already clean (no mL on solid):        {summary['already_clean']}")
    print(f"Cleared mL only (g already present):   {summary['cleared_mL_only']}")
    print(f"Converted mL → g via density:          {summary['converted_mL_to_g']}")
    if summary["touched_items"]:
        print()
        print("Lots modified:")
        for row in summary["touched_items"]:
            iid, code, name, action = row
            print(f"  - id={iid}  {code!r}  ({name})  {action}")
    print("=" * 64)


if __name__ == "__main__":
    from stoic_eln import create_app

    app = create_app()
    with app.app_context():
        result = main()
        print_summary(result)
