"""Stoic ELN — One-shot migration: propagate missing g/mL via density.

Run once after deploying the inventory g/mL policy patch.

Walks every active substance-backed InventoryItem and, when the
substance has a density set, propagates the missing unit from the
populated one. Concretely fixes the original bug reported in
testing:

  - Hexanoyl chloride has density=0.9763 g/mL
  - A lot was created with quantity_g=100 and quantity_mL=NULL
  - The next run tries to consume in mL → "0 mL disponibili"

After this script: quantity_mL becomes 102.43 (≈ 100 / 0.9763) and
the run can proceed.

Idempotent: re-running is safe. Only touches rows where exactly one
of g/mL is set; rows where both are populated are inspected for
consistency and reported but not modified (the user may have set
both intentionally — leave the human in charge).

Mixture lots are NOT touched (the matrix doesn't apply to them).

Usage:
    cd ~/Projects/stoic-eln
    export FLASK_APP=stoic_eln
    .venv/bin/flask shell <<'PY'
    exec(open('scripts/migrate_inventory_quantity_policy.py').read())
    PY

Or:
    .venv/bin/python -m scripts.migrate_inventory_quantity_policy
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models import InventoryItem
from stoic_eln.services.inventory_quantity import (
    policy_for_substance,
    _CONSISTENCY_TOL,
)


def _propagate_pair(
    g: float | None, mL: float | None, density: float
) -> tuple[float | None, float | None, str]:
    """Returns (g, mL, status). status is one of:
    'unchanged', 'filled_mL', 'filled_g', 'inconsistent', 'empty'.
    """
    if g is None and mL is None:
        return None, None, "empty"
    if g is not None and mL is None:
        return g, round(g / density, 6), "filled_mL"
    if g is None and mL is not None:
        return round(mL * density, 6), mL, "filled_g"
    # Both set — check consistency
    expected_mL = g / density
    if expected_mL <= 0:
        return g, mL, "unchanged"
    delta = abs(mL - expected_mL) / expected_mL
    if delta > _CONSISTENCY_TOL:
        return g, mL, "inconsistent"
    return g, mL, "unchanged"


def main() -> dict:
    """Run the migration. Returns a summary dict for inspection."""
    summary = {
        "scanned": 0,
        "skipped_mixture": 0,
        "skipped_no_substance": 0,
        "skipped_no_density": 0,
        "skipped_solvent_no_density": 0,
        "fixed": 0,
        "inconsistent": [],  # list of (id, reason)
        "already_consistent": 0,
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

        policy = policy_for_substance(sub)

        if not policy.synced:
            # Single-unit cases: nothing to propagate. Reports for
            # visibility but not as an action.
            if policy.is_solvent_no_density:
                summary["skipped_solvent_no_density"] += 1
            else:
                summary["skipped_no_density"] += 1
            continue

        density = policy.density

        # Initial pair
        new_init_g, new_init_mL, init_status = _propagate_pair(
            it.initial_quantity_g, it.initial_quantity_mL, density
        )
        # Remaining pair
        new_rem_g, new_rem_mL, rem_status = _propagate_pair(it.quantity_g, it.quantity_mL, density)

        changed = False
        if init_status in ("filled_mL", "filled_g"):
            it.initial_quantity_g = new_init_g
            it.initial_quantity_mL = new_init_mL
            changed = True
        if rem_status in ("filled_mL", "filled_g"):
            it.quantity_g = new_rem_g
            it.quantity_mL = new_rem_mL
            changed = True

        if init_status == "inconsistent" or rem_status == "inconsistent":
            summary["inconsistent"].append((it.id, init_status, rem_status, it.batch_code))

        if changed:
            summary["fixed"] += 1
        elif init_status == "unchanged" and rem_status == "unchanged":
            summary["already_consistent"] += 1

    db.session.commit()
    return summary


def print_summary(summary: dict) -> None:
    print("=" * 60)
    print("Inventory quantity policy migration — summary")
    print("=" * 60)
    print(f"Scanned active lots:              {summary['scanned']}")
    print(f"Skipped (mixture lot):            {summary['skipped_mixture']}")
    print(f"Skipped (no substance):           {summary['skipped_no_substance']}")
    print(f"Skipped (reagent, no density):    {summary['skipped_no_density']}")
    print(f"Skipped (solvent, no density):    {summary['skipped_solvent_no_density']}")
    print(f"Already consistent:               {summary['already_consistent']}")
    print(f"Fixed (propagated via density):   {summary['fixed']}")
    if summary["inconsistent"]:
        print()
        print("Inconsistent rows (NOT fixed; review manually):")
        for row in summary["inconsistent"]:
            item_id, init_st, rem_st, code = row
            print(f"  - id={item_id} code={code!r} init={init_st} rem={rem_st}")
    print("=" * 60)


if __name__ == "__main__":
    # Allow running via: python -m scripts.migrate_inventory_quantity_policy
    from stoic_eln import create_app

    app = create_app()
    with app.app_context():
        result = main()
        print_summary(result)
