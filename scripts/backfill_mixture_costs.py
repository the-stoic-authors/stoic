"""Stoic ELN — CLI wrapper for the mixture-cost backfill.

The domain logic lives in ``stoic_eln.services.backfill``; this script only
handles argument parsing, app setup and printing. See the service module for
the full description of what the backfill does.

**Dry-run by default** — prints what *would* change without writing.

    .venv/bin/python scripts/backfill_mixture_costs.py            # preview
    .venv/bin/python scripts/backfill_mixture_costs.py --apply    # write

Safe to re-run: only lots with no cost are touched.
"""

from __future__ import annotations

import sys

from stoic_eln import create_app
from stoic_eln.services.backfill import run_backfill


def main() -> None:
    apply = "--apply" in sys.argv
    app = create_app()
    with app.app_context():
        s = run_backfill(apply=apply)
        total = len(s["priced"]) + len(s["no_prep"]) + len(s["unpriced"])
        print(f"Mixture lots without a cost: {total}")
        print(f"  priced now : {len(s['priced'])}")
        for lot, cost, n_priced, n_total in s["priced"]:
            tag = "" if n_priced == n_total else f"  (partial: {n_priced}/{n_total} priced)"
            print(f"    {lot.batch_code or lot.id}: {cost:.2f} EUR{tag}")
        print(f"  no prep    : {len(s['no_prep'])}  (manually-added lots, skipped)")
        print(f"  no price   : {len(s['unpriced'])}  (no priced precursor)")
        if apply:
            print("Committed.")
        else:
            print("Dry-run — nothing written. Re-run with --apply to commit.")


if __name__ == "__main__":
    main()
