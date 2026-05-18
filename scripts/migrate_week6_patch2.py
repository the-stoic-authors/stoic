"""Stoic ELN — Migration: Settimana 6 patch 2 — Low-stock thresholds.

Adds two new columns to the ``substance`` table:
  - low_stock_threshold_g   FLOAT NULL
  - low_stock_threshold_mL  FLOAT NULL

NULL means no threshold; the substance does not appear in the
dashboard's low-stock alerts. Set per-substance via the substance
detail page.

Idempotent: safe to re-run.
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
    return column in {c["name"] for c in insp.get_columns(table)}


def main() -> int:
    app = create_app()
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        actions: list[str] = []

        for col_name in ("low_stock_threshold_g", "low_stock_threshold_mL"):
            if not _has_column(insp, "substance", col_name):
                with engine.begin() as conn:
                    conn.execute(text(
                        f"ALTER TABLE substance ADD COLUMN {col_name} FLOAT"
                    ))
                actions.append(f"Added substance.{col_name}")
            else:
                actions.append(
                    f"substance.{col_name} already present, skipped"
                )

        for line in actions:
            print(f"  • {line}")
        print("\nMigration complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
