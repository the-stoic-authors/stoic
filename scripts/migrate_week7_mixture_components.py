"""Stoic ELN — Migration: Settimana 7 — mixture-as-component.

Adds support for using one ``Mixture`` as a component of another
(e.g. HCl 12N stock used to prepare HCl 6N). The schema change:

  mixture_component.substance_id          → made NULLABLE
  mixture_component.child_mixture_id      → NEW column, INTEGER FK to mixture(id)
  CHECK ck_mixture_component_xor          → exactly one of the two is set

SQLite doesn't support ALTER COLUMN to change nullability or add a
CHECK constraint cleanly, so we use the standard table-swap pattern:

  1. Create ``mixture_component__new`` with the target schema.
  2. Copy all rows from the old table — they all have substance_id
     set and child_mixture_id will be NULL, which satisfies XOR.
  3. DROP the old table.
  4. RENAME __new → original.
  5. Recreate indexes.

Idempotent: detects if the migration has already run (presence of
``child_mixture_id`` column) and skips. Safe to re-run.

Usage:
    python scripts/migrate_week7_mixture_components.py
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


def main() -> None:
    app = create_app()
    with app.app_context():
        insp = inspect(db.engine)
        actions: list[str] = []

        if "mixture_component" not in insp.get_table_names():
            print(
                "ERROR: 'mixture_component' table not found. "
                "Apply Settimana 5 (mixtures) first."
            )
            sys.exit(1)

        if _has_column(insp, "mixture_component", "child_mixture_id"):
            print(
                "Migration already applied — "
                "'mixture_component.child_mixture_id' column exists. "
                "Nothing to do."
            )
            return

        # Table swap. The entire operation runs in one transaction:
        # if anything fails, the old table stays intact.
        with db.engine.begin() as conn:
            # 1. New table with target schema. Note the XOR CHECK
            # constraint expressed as a CASE-WHEN sum since SQLite
            # doesn't support the cleaner `(a IS NULL) <> (b IS NULL)`
            # syntax across all versions.
            conn.execute(text("""
                CREATE TABLE mixture_component__new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mixture_id INTEGER NOT NULL REFERENCES mixture(id),
                    substance_id INTEGER REFERENCES substance(id),
                    child_mixture_id INTEGER REFERENCES mixture(id),
                    role VARCHAR(24) NOT NULL DEFAULT 'solute',
                    concentration FLOAT,
                    concentration_unit VARCHAR(16),
                    position INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    CONSTRAINT ck_mixture_component_xor
                        CHECK (
                            (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                            (CASE WHEN child_mixture_id IS NULL THEN 0 ELSE 1 END) = 1
                        )
                )
            """))
            actions.append("Created mixture_component__new with XOR constraint")

            # 2. Copy data. All existing rows have substance_id set
            # and child_mixture_id NULL (the new column), which
            # satisfies the XOR check.
            conn.execute(text("""
                INSERT INTO mixture_component__new (
                    id, mixture_id, substance_id, child_mixture_id,
                    role, concentration, concentration_unit,
                    position, notes
                )
                SELECT
                    id, mixture_id, substance_id, NULL AS child_mixture_id,
                    role, concentration, concentration_unit,
                    position, notes
                FROM mixture_component
            """))
            count_result = conn.execute(text(
                "SELECT COUNT(*) FROM mixture_component__new"
            ))
            row_count = count_result.scalar()
            actions.append(f"Copied {row_count} rows from old table")

            # 3. Swap.
            conn.execute(text("DROP TABLE mixture_component"))
            conn.execute(text(
                "ALTER TABLE mixture_component__new "
                "RENAME TO mixture_component"
            ))
            actions.append("Swapped new table into place")

            # 4. Recreate indexes (the ORM's canonical set). The
            # ``index=True`` columns in the model are: mixture_id,
            # substance_id, child_mixture_id.
            conn.execute(text(
                "CREATE INDEX ix_mixture_component_mixture_id "
                "ON mixture_component(mixture_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_mixture_component_substance_id "
                "ON mixture_component(substance_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_mixture_component_child_mixture_id "
                "ON mixture_component(child_mixture_id)"
            ))
            actions.append("Recreated 3 indexes")

        print("Migration completed:")
        for a in actions:
            print(f"  - {a}")
        print()
        print("You can now restart the app: make run")
        print()
        print("New capability: when editing a Mixture, you can now")
        print("choose 'Miscela' as a component kind (instead of just")
        print("'Sostanza'). Useful e.g. for HCl 6N prepared from HCl 12N.")


if __name__ == "__main__":
    main()
