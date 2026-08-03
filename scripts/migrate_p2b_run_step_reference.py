"""Stoic ELN — Migration: P2b run-step reference snapshot.

Schema change (single, trivial):
  ``run_step``: add ``reference_run_component_id`` INTEGER NULL,
  FK → ``run_component(id)`` ON DELETE SET NULL.

This is a plain nullable ADD COLUMN — ``run_step`` carries no CHECK
constraint, so no table rebuild is needed (unlike the P2 migration).
SQLite adds the column in place. Existing runs get NULL, which the
step calculator already treats as "fall back to the limiting reagent",
so historical runs are unchanged.

Idempotent: presence of the column is the marker.

Run with:  .venv/bin/python scripts/migrate_p2b_run_step_reference.py
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def migrate() -> None:
    app = create_app()
    with app.app_context():
        insp = inspect(db.engine)

        if "run_step" not in insp.get_table_names():
            print("run_step table not present — nothing to migrate "
                  "(a fresh `flask ensure-schema` will create it correctly).")
            return

        if _has_column(insp, "run_step", "reference_run_component_id"):
            print("run_step.reference_run_component_id already present — skipping.")
            return

        with db.engine.begin() as conn:
            # SQLite supports ADD COLUMN with a column-level REFERENCES
            # clause; ON DELETE SET NULL matches the model.
            conn.execute(
                text(
                    "ALTER TABLE run_step ADD COLUMN reference_run_component_id "
                    "INTEGER REFERENCES run_component (id) ON DELETE SET NULL"
                )
            )
        print("Added run_step.reference_run_component_id.")


if __name__ == "__main__":
    migrate()
