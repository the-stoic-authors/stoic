"""Stoic ELN — Migration: Settimana 6 patch 13.0 — Mixtures.

Introduces the ``mixture`` and ``mixture_component`` tables for
tracking lab preparations (solutions, eluents, buffers,
reagent mixes), and adapts ``inventory_item`` so a lot can belong
either to a pure ``Substance`` or to a ``Mixture``.

Schema changes:

1. Create ``mixture`` and ``mixture_component`` tables.

2. Add ``inventory_item.mixture_id`` (nullable FK to ``mixture``).

3. Relax ``inventory_item.substance_id`` from NOT NULL to NULL — a
   lot of a mixture has no direct substance link.

4. Add a CHECK constraint
   ``ck_inventory_item_substance_xor_mixture`` enforcing that
   exactly one of ``substance_id`` / ``mixture_id`` is set on every
   row.

The migration is **idempotent**: re-running it skips already-applied
steps. Existing rows are not modified — they keep their
``substance_id`` and ``mixture_id`` stays NULL, which satisfies the
XOR constraint.

SQLite implementation note: SQLite cannot ALTER a column's nullability
in place. We rebuild ``inventory_item`` table-as-a-whole (create new
table, copy data, drop old, rename new) when relaxing the nullability.
PostgreSQL deployments can do this with a plain ALTER TABLE; this
script handles SQLite via the rebuild path because Stoic's reference
deployment is SQLite.
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _column_is_nullable(insp, table: str, column: str) -> bool:
    """Inspector-based check: is ``table.column`` nullable?

    Returns True if not-found, so callers treat "missing column" the
    same as "doesn't need fixing" (the schema rebuild step will
    create it from scratch).
    """
    cols = insp.get_columns(table)
    for c in cols:
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

        # ── 1. mixture table ─────────────────────────────────────────
        if "mixture" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE mixture (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(200) NOT NULL,
                        kind VARCHAR(24) NOT NULL DEFAULT 'solution',
                        description TEXT,
                        primary_concentration FLOAT,
                        primary_concentration_unit VARCHAR(16),
                        primary_solvent_id INTEGER REFERENCES substance(id),
                        ghs_pictograms_override JSON,
                        h_phrases_override JSON,
                        p_phrases_override JSON,
                        group_id INTEGER REFERENCES "group"(id),
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        notes TEXT,
                        created_by_id INTEGER REFERENCES user(id),
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_name ON mixture(name)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_kind ON mixture(kind)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_group_id ON mixture(group_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_is_active ON mixture(is_active)"
                ))
            actions.append("created table mixture (+4 indexes)")
        else:
            actions.append("table mixture already exists — skipped")

        # ── 2. mixture_component table ───────────────────────────────
        # Refresh the inspector after the previous step's commit.
        insp = inspect(engine)
        if "mixture_component" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE mixture_component (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        mixture_id INTEGER NOT NULL REFERENCES mixture(id),
                        substance_id INTEGER NOT NULL REFERENCES substance(id),
                        role VARCHAR(24) NOT NULL DEFAULT 'solute',
                        concentration FLOAT,
                        concentration_unit VARCHAR(16),
                        position INTEGER NOT NULL DEFAULT 0,
                        notes TEXT
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_component_mixture_id "
                    "ON mixture_component(mixture_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_mixture_component_substance_id "
                    "ON mixture_component(substance_id)"
                ))
            actions.append("created table mixture_component (+2 indexes)")
        else:
            actions.append("table mixture_component already exists — skipped")

        # ── 3. inventory_item: add mixture_id + relax substance_id ──
        #
        # We do both column changes in one pass via SQLite's
        # "rebuild the table" idiom. This is necessary because:
        #
        #   - SQLite < 3.35 cannot ALTER COLUMN to relax NOT NULL.
        #   - Even with ADD COLUMN for ``mixture_id`` we'd still
        #     need to add the CHECK constraint, which SQLite can
        #     only do at table-creation time.
        #
        # We detect whether the rebuild is needed by inspecting
        # both: if substance_id is already nullable AND mixture_id
        # exists, nothing to do.
        insp = inspect(engine)
        needs_rebuild = (
            "inventory_item" in insp.get_table_names()
            and (
                not _column_is_nullable(insp, "inventory_item", "substance_id")
                or not _has_column(insp, "inventory_item", "mixture_id")
            )
        )

        if needs_rebuild:
            # Rebuild via temp table. We list columns explicitly
            # rather than SELECT * so adding new columns later
            # doesn't break the migration.
            with engine.begin() as conn:
                # Disable foreign keys during the rebuild so the temp
                # rename doesn't cascade-validate. Re-enable after.
                conn.execute(text("PRAGMA foreign_keys=OFF"))

                # 3a. Create the new table with the desired schema.
                conn.execute(text("""
                    CREATE TABLE inventory_item__new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        substance_id INTEGER REFERENCES substance(id),
                        mixture_id INTEGER REFERENCES mixture(id),
                        batch_code VARCHAR(64),
                        supplier VARCHAR(120),
                        catalogue_number VARCHAR(64),
                        quantity_g FLOAT,
                        quantity_mL FLOAT,
                        initial_quantity_g FLOAT,
                        initial_quantity_mL FLOAT,
                        total_cost_eur FLOAT,
                        purchased_at DATE,
                        expiry_date DATE,
                        location VARCHAR(200),
                        source_run_id INTEGER,
                        group_id INTEGER NOT NULL REFERENCES "group"(id),
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        notes TEXT,
                        created_by_id INTEGER REFERENCES user(id),
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        CONSTRAINT ck_inventory_item_substance_xor_mixture
                            CHECK (
                                (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                                (CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1
                            )
                    )
                """))

                # 3b. Copy data. Existing rows have substance_id set
                # and mixture_id NULL (the new column defaults to
                # NULL), satisfying the CHECK.
                conn.execute(text("""
                    INSERT INTO inventory_item__new (
                        id, substance_id, mixture_id, batch_code, supplier,
                        catalogue_number, quantity_g, quantity_mL,
                        initial_quantity_g, initial_quantity_mL, total_cost_eur,
                        purchased_at, expiry_date, location, source_run_id,
                        group_id, is_active, notes, created_by_id,
                        created_at, updated_at
                    )
                    SELECT
                        id, substance_id, NULL AS mixture_id, batch_code, supplier,
                        catalogue_number, quantity_g, quantity_mL,
                        initial_quantity_g, initial_quantity_mL, total_cost_eur,
                        purchased_at, expiry_date, location, source_run_id,
                        group_id, is_active, notes, created_by_id,
                        created_at, updated_at
                    FROM inventory_item
                """))

                # 3c. Swap.
                conn.execute(text("DROP TABLE inventory_item"))
                conn.execute(text(
                    "ALTER TABLE inventory_item__new RENAME TO inventory_item"
                ))

                # 3d. Recreate indexes that were on the old table.
                # SQLAlchemy's inspector normally tells us about them,
                # but easier to just recreate the canonical set the
                # ORM expects.
                conn.execute(text(
                    "CREATE INDEX ix_inventory_item_substance_id "
                    "ON inventory_item(substance_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_inventory_item_mixture_id "
                    "ON inventory_item(mixture_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_inventory_item_batch_code "
                    "ON inventory_item(batch_code)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_inventory_item_location "
                    "ON inventory_item(location)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_inventory_item_group_id "
                    "ON inventory_item(group_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_inventory_item_is_active "
                    "ON inventory_item(is_active)"
                ))

                conn.execute(text("PRAGMA foreign_keys=ON"))

            actions.append(
                "rebuilt inventory_item (substance_id nullable, "
                "added mixture_id, added XOR check)"
            )
        else:
            actions.append(
                "inventory_item already migrated (substance_id nullable, "
                "mixture_id present) — skipped"
            )

        # Final create_all() for any tables/indexes the ORM expects
        # but the manual SQL above didn't enumerate.
        db.create_all()

        print("Migration patch 13.0 complete. Actions:")
        for a in actions:
            print(f"  - {a}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
