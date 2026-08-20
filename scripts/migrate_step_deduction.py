"""Stoic ELN — Migration: step-component inventory deduction (v1.4.4).

Adds three nullable columns to ``run_step_component``:

    deducted_lot_id      INTEGER   — which lot this component is holding from
    deducted_mass_g      FLOAT     — how much of it, mass channel
    deducted_volume_mL   FLOAT     — how much of it, volume channel

They let a step component's consumption be reconciled incrementally
while the run is in progress: on every edit only the difference against
what was already taken is moved, so corrections give quantity back and
lot swaps carry the deduction across.

The actual work lives in ``stoic_eln.services.schema_migrations`` so the
same logic is reachable as ``flask migrate-step-deduction`` — which,
unlike this script, is present inside the Docker image.

Run with:
    .venv/bin/python scripts/migrate_step_deduction.py

Or, equivalently:
    export FLASK_APP=stoic_eln
    .venv/bin/flask migrate-step-deduction
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402
from stoic_eln.services.schema_migrations import ensure_step_deduction_columns  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        actions = ensure_step_deduction_columns(db.engine)
    print("Migration complete:")
    for a in actions:
        print("  -", a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
