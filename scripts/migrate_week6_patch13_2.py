"""Stoic ELN — Migration: Settimana 6 patch 13.2.0 — MixturePrep tables.

Adds tables ``mixture_prep`` and ``mixture_prep_consumption`` for
tracking the act of preparing a mixture from precursor lots
(diluting HCl 12N to 6N, mixing eluent A 95:5, etc.).

Idempotent: re-running it skips already-created tables.

No changes to existing tables — purely additive.
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

        if "mixture_prep" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE mixture_prep (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code VARCHAR(80) NOT NULL UNIQUE,
                        sequence INTEGER NOT NULL DEFAULT 1,
                        year INTEGER NOT NULL,
                        mixture_id INTEGER NOT NULL REFERENCES mixture(id),
                        target_quantity FLOAT NOT NULL,
                        target_quantity_unit VARCHAR(8) NOT NULL,
                        output_inventory_item_id INTEGER REFERENCES inventory_item(id),
                        prepared_by_id INTEGER REFERENCES user(id),
                        prepared_at DATETIME NOT NULL,
                        notes TEXT,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_prep_code ON mixture_prep(code)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_prep_sequence "
                    "ON mixture_prep(sequence)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_prep_year ON mixture_prep(year)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_prep_mixture_id "
                    "ON mixture_prep(mixture_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_prep_output "
                    "ON mixture_prep(output_inventory_item_id)"
                ))
            actions.append("created table mixture_prep (+5 indexes)")
        else:
            actions.append("table mixture_prep already exists — skipped")

        # Refresh inspector after potential commit
        insp = inspect(engine)
        if "mixture_prep_consumption" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE mixture_prep_consumption (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prep_id INTEGER NOT NULL REFERENCES mixture_prep(id),
                        inventory_item_id INTEGER NOT NULL
                            REFERENCES inventory_item(id),
                        quantity_consumed FLOAT NOT NULL,
                        quantity_unit VARCHAR(8) NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        notes TEXT
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_mpc_prep_id "
                    "ON mixture_prep_consumption(prep_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mpc_inventory_item_id "
                    "ON mixture_prep_consumption(inventory_item_id)"
                ))
            actions.append(
                "created table mixture_prep_consumption (+2 indexes)"
            )
        else:
            actions.append(
                "table mixture_prep_consumption already exists — skipped"
            )

        # Final create_all to pick up anything the ORM expects but
        # the manual CREATE didn't enumerate.
        db.create_all()

        print("Migration patch 13.2.0 complete. Actions:")
        for a in actions:
            print(f"  - {a}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
