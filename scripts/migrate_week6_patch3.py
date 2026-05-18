"""Stoic ELN — Migration: Settimana 6 patch 3 — Orders.

Creates the ``purchase_order`` table to track planned and in-progress
purchases (one record per lot to be acquired).

Idempotent: safe to re-run.
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        actions: list[str] = []

        if "purchase_order" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE purchase_order (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        substance_id INTEGER NOT NULL REFERENCES substance(id),
                        group_id INTEGER NOT NULL REFERENCES "group"(id),
                        supplier VARCHAR(120),
                        catalogue_number VARCHAR(64),
                        ordered_quantity_g FLOAT,
                        ordered_quantity_mL FLOAT,
                        ordered_total_eur FLOAT,
                        currency VARCHAR(8) NOT NULL DEFAULT 'EUR',
                        ordered_at DATE,
                        expected_delivery_date DATE,
                        received_at DATE,
                        received_quantity_g FLOAT,
                        received_quantity_mL FLOAT,
                        received_total_eur FLOAT,
                        internal_order_ref VARCHAR(64),
                        status VARCHAR(24) NOT NULL DEFAULT 'planned',
                        notes TEXT,
                        inventory_item_id INTEGER REFERENCES inventory_item(id),
                        created_by_id INTEGER REFERENCES user(id),
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_purchase_order_substance "
                    "ON purchase_order(substance_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_purchase_order_group "
                    "ON purchase_order(group_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_purchase_order_status "
                    "ON purchase_order(status)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_purchase_order_inventory_item "
                    "ON purchase_order(inventory_item_id)"
                ))
            actions.append("Created table 'purchase_order'")
        else:
            actions.append("Table 'purchase_order' already present, skipped")

        for line in actions:
            print(f"  • {line}")
        print("\nMigration complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
