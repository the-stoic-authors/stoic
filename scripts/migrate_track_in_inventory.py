"""Stoic ELN — Migration: track_in_inventory flag on products/byproducts.

Adds a boolean column ``track_in_inventory`` to both ``reaction_component``
and ``run_component``. It controls whether a product/byproduct creates an
inventory lot on run completion:

  - products default to True  (they are what you make → stock them)
  - byproducts default to False (usually waste, e.g. NaHSO4 from HCl
    generation → don't fill the inventory with them)

The column itself defaults to 1 (True) so existing rows and non-product
roles keep the historical behaviour. Per-role defaults for NEW components
are applied in the reaction form/route, not here.

SQLite supports ``ALTER TABLE ... ADD COLUMN`` with a constant default in
place (no table rebuild needed), so this migration is a simple, idempotent
add-column.

Run with:
    .venv/bin/python scripts/migrate_track_in_inventory.py
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def main() -> int:
    app = create_app()
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        actions: list[str] = []

        for table in ("reaction_component", "run_component"):
            if table not in insp.get_table_names():
                actions.append(f"table {table} absent — db.create_all will create it")
                continue
            if _has_column(insp, table, "track_in_inventory"):
                actions.append(f"{table}.track_in_inventory already present — skip")
                continue
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"ALTER TABLE {table} "
                        "ADD COLUMN track_in_inventory BOOLEAN NOT NULL DEFAULT 1"
                    )
                )
            actions.append(f"{table}.track_in_inventory added (default 1)")

        print("Migration complete:")
        for a in actions:
            print("  -", a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
