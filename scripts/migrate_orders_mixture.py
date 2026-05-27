"""Stoic ELN — Migration: Plan-order su Mixture.

Extends ``purchase_order`` to support orders of Mixture (commercial
preparations like HCl 12N, NaOH 1M, PBS pH 7.4) in addition to
Substance.

Schema changes:
  - ``substance_id``: NOT NULL → nullable
  - new column ``mixture_id``: nullable, FK to mixture(id), indexed
  - new CHECK constraint ``ck_purchase_order_substance_xor_mixture``:
    exactly one of (substance_id, mixture_id) must be set

Idempotent. Uses SQLite's "table rebuild" idiom because SQLite cannot
ALTER a column to relax NOT NULL or add a CHECK constraint in place.

Existing rows preserve ``substance_id`` and end up with
``mixture_id=NULL`` — which satisfies the new XOR check.

Run with:
    .venv/bin/python scripts/migrate_orders_mixture.py
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _column_is_nullable(insp, table: str, column: str) -> bool:
    for c in insp.get_columns(table):
        if c["name"] == column:
            return bool(c["nullable"])
    return True


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def main() -> int:
    app = create_app()
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        actions: list[str] = []

        # ── purchase_order ───────────────────────────────────────
        if "purchase_order" not in insp.get_table_names():
            actions.append("table purchase_order absent — db.create_all will create it")
        else:
            needs_rebuild = not _column_is_nullable(
                insp, "purchase_order", "substance_id"
            ) or not _has_column(insp, "purchase_order", "mixture_id")
            if needs_rebuild:
                with engine.begin() as conn:
                    conn.execute(text("PRAGMA foreign_keys=OFF"))
                    conn.execute(
                        text("""
                        CREATE TABLE purchase_order__new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            substance_id INTEGER REFERENCES substance(id),
                            mixture_id INTEGER REFERENCES mixture(id),
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
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            CONSTRAINT ck_purchase_order_substance_xor_mixture
                                CHECK (
                                    (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                                    (CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1
                                )
                        )
                    """)
                    )
                    conn.execute(
                        text("""
                        INSERT INTO purchase_order__new (
                            id, substance_id, mixture_id, group_id,
                            supplier, catalogue_number,
                            ordered_quantity_g, ordered_quantity_mL,
                            ordered_total_eur, currency,
                            ordered_at, expected_delivery_date, received_at,
                            received_quantity_g, received_quantity_mL,
                            received_total_eur, internal_order_ref,
                            status, notes, inventory_item_id,
                            created_by_id, created_at, updated_at
                        )
                        SELECT
                            id, substance_id, NULL, group_id,
                            supplier, catalogue_number,
                            ordered_quantity_g, ordered_quantity_mL,
                            ordered_total_eur, currency,
                            ordered_at, expected_delivery_date, received_at,
                            received_quantity_g, received_quantity_mL,
                            received_total_eur, internal_order_ref,
                            status, notes, inventory_item_id,
                            created_by_id, created_at, updated_at
                        FROM purchase_order
                    """)
                    )
                    conn.execute(text("DROP TABLE purchase_order"))
                    conn.execute(text("ALTER TABLE purchase_order__new RENAME TO purchase_order"))
                    # Recreate the indices that were on the original table
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_purchase_order_substance_id "
                            "ON purchase_order(substance_id)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_purchase_order_mixture_id "
                            "ON purchase_order(mixture_id)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_purchase_order_group_id "
                            "ON purchase_order(group_id)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_purchase_order_status "
                            "ON purchase_order(status)"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_purchase_order_inventory_item_id "
                            "ON purchase_order(inventory_item_id)"
                        )
                    )
                    conn.execute(text("PRAGMA foreign_keys=ON"))
                actions.append(
                    "purchase_order rebuilt: substance_id nullable, "
                    "mixture_id added, XOR check added"
                )
            else:
                actions.append("purchase_order already up to date")

        if actions:
            print("Migration actions:")
            for a in actions:
                print(f"  • {a}")
        else:
            print("Nothing to do — schema already up to date.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
