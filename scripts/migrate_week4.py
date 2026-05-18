"""Stoic ELN — Migration: Settimana 4 — Run + RunComponent + RunStep…

Adds 5 new tables for the Run lifecycle:
  - run                  : top-level execution record
  - run_component        : substance + lot + target/actual amounts
  - run_step             : snapshot of ReactionStep
  - run_step_component   : snapshot of ReactionStepComponent
  - run_checklist_item   : per-run checkable list items

Idempotent: safe to re-run, no data loss.

Usage:
    python scripts/migrate_week4.py
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)

        existing = set(insp.get_table_names())
        new_tables = [
            "run",
            "run_component",
            "run_step",
            "run_step_component",
            "run_checklist_item",
        ]
        missing = [t for t in new_tables if t not in existing]
        if missing:
            print(f"  • Creating tables: {', '.join(missing)}")
            # SQLAlchemy create_all only creates tables that don't exist yet.
            db.create_all()
        else:
            print("  • All run-related tables already present, nothing to do.")

        print("\nMigration complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
