"""Stoic ELN — Migration: Settimana 3 (rebuild) ← Settimana 3 (initial).

Idempotent migration: applies only the deltas needed to upgrade the database
from the first Settimana 3 build to the rebuild that adds:

  - reaction.default_scale_mmol  (new column)
  - checklist_item               (new table)
  - reaction_step                (new table)
  - reaction_step_component      (new table)

This script does NOT touch existing data (users, substances, lots, hazard
phrases, reactions, components). Run it once after extracting the new tarball.

Usage:
    python scripts/migrate_week3_rebuild.py

If a column or table already exists, it is skipped silently. So the script is
safe to re-run.
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

# Make sure we can import the app package
sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _has_column(insp, table: str, column: str) -> bool:
    if table not in insp.get_table_names():
        return False
    cols = {c["name"] for c in insp.get_columns(table)}
    return column in cols


def _has_table(insp, table: str) -> bool:
    return table in insp.get_table_names()


def main() -> None:
    app = create_app()
    with app.app_context():
        insp = inspect(db.engine)

        actions: list[str] = []

        # 1. Add reaction.default_scale_mmol if missing
        if not _has_table(insp, "reaction"):
            print(
                "ERROR: 'reaction' table not found. You appear to be running this "
                "before applying Settimana 3. Run scripts/init_db.py first."
            )
            sys.exit(1)

        if not _has_column(insp, "reaction", "default_scale_mmol"):
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE reaction "
                        "ADD COLUMN default_scale_mmol FLOAT NOT NULL DEFAULT 1.0"
                    )
                )
            actions.append("Added column reaction.default_scale_mmol")
        else:
            actions.append("Skipped: reaction.default_scale_mmol already present")

        # 2. Create new tables via SQLAlchemy metadata (idempotent: only creates
        #    tables that don't already exist)
        from stoic_eln.models.checklist_item import ChecklistItem
        from stoic_eln.models.reaction_step import ReactionStep
        from stoic_eln.models.reaction_step_component import ReactionStepComponent

        # We need to refresh the inspector after the ALTER above
        insp = inspect(db.engine)

        new_tables = [
            ("reaction_step", ReactionStep.__table__),
            ("reaction_step_component", ReactionStepComponent.__table__),
            ("checklist_item", ChecklistItem.__table__),
        ]

        for name, tbl in new_tables:
            if _has_table(insp, name):
                actions.append(f"Skipped: table {name} already present")
            else:
                tbl.create(bind=db.engine)
                actions.append(f"Created table {name}")

        print("Migration completed:")
        for a in actions:
            print(f"  - {a}")
        print()
        print("You can now restart the app: make run")


if __name__ == "__main__":
    main()
