"""Stoic ELN — Migration: Settimana 4 patch 3 — scale input remembered.

Adds two columns to the ``run`` table to remember the exact value+unit
the operator entered when setting the scale (so we can re-display it
instead of always showing mmol):

  - scale_input_value : FLOAT NULL
  - scale_input_unit  : VARCHAR(8) NULL

Idempotent: safe to re-run, no data loss.

Usage:
    python scripts/migrate_week4_patch3.py
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _has_column(insp, table: str, column: str) -> bool:
    if table not in insp.get_table_names():
        return False
    cols = {c["name"] for c in insp.get_columns(table)}
    return column in cols


def main() -> int:
    app = create_app()
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)

        actions: list[str] = []

        if not _has_column(insp, "run", "scale_input_value"):
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE run ADD COLUMN scale_input_value FLOAT"
                ))
            actions.append("Added run.scale_input_value")
        else:
            actions.append("run.scale_input_value already present, skipped")

        if not _has_column(insp, "run", "scale_input_unit"):
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE run ADD COLUMN scale_input_unit VARCHAR(8)"
                ))
            actions.append("Added run.scale_input_unit")
        else:
            actions.append("run.scale_input_unit already present, skipped")

        for line in actions:
            print(f"  • {line}")
        print("\nMigration complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
