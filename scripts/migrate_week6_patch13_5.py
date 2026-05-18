"""Stoic ELN — Migration: Settimana 6 patch 13.5 — Reaction & Run
components can reference Mixtures.

Schema changes:
  1. ``reaction_component.substance_id`` → nullable, add ``mixture_id``,
     add XOR check constraint.
  2. ``run_component.substance_id``      → nullable, add ``mixture_id``,
     add XOR check constraint.

Idempotent. Uses the same SQLite table-rebuild idiom as patch 13.0.
Existing rows preserve their ``substance_id`` and end up with
``mixture_id=NULL`` — satisfies the XOR check.
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

        if "reaction_component" not in insp.get_table_names():
            # Fresh DB without reactions feature yet — db.create_all()
            # below will create everything in the new shape.
            actions.append(
                "table reaction_component absent — db.create_all will create it"
            )
        else:
            needs_rebuild = (
                not _column_is_nullable(insp, "reaction_component", "substance_id")
                or not _has_column(insp, "reaction_component", "mixture_id")
            )
            if needs_rebuild:
                with engine.begin() as conn:
                    conn.execute(text("PRAGMA foreign_keys=OFF"))

                    # 1. New table with target schema.
                    conn.execute(text("""
                        CREATE TABLE reaction_component__new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            reaction_id INTEGER NOT NULL REFERENCES reaction(id),
                            substance_id INTEGER REFERENCES substance(id),
                            mixture_id INTEGER REFERENCES mixture(id),
                            role VARCHAR(40) NOT NULL DEFAULT 'reactant',
                            position INTEGER NOT NULL DEFAULT 0,
                            equivalents FLOAT,
                            amount_mmol FLOAT,
                            amount_g FLOAT,
                            amount_mL FLOAT,
                            is_limiting BOOLEAN NOT NULL DEFAULT 0,
                            concentration_M FLOAT,
                            notes TEXT,
                            created_at DATETIME NOT NULL,
                            CONSTRAINT ck_reaction_component_substance_xor_mixture
                                CHECK (
                                    (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                                    (CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1
                                )
                        )
                    """))

                    # 2. Copy data — existing rows have substance_id and
                    # NULL mixture_id, which satisfies the XOR check.
                    conn.execute(text("""
                        INSERT INTO reaction_component__new (
                            id, reaction_id, substance_id, mixture_id,
                            role, position,
                            equivalents, amount_mmol, amount_g, amount_mL,
                            is_limiting, concentration_M, notes, created_at
                        )
                        SELECT
                            id, reaction_id, substance_id, NULL AS mixture_id,
                            role, position,
                            equivalents, amount_mmol, amount_g, amount_mL,
                            is_limiting, concentration_M, notes, created_at
                        FROM reaction_component
                    """))

                    # 3. Swap.
                    conn.execute(text("DROP TABLE reaction_component"))
                    conn.execute(text(
                        "ALTER TABLE reaction_component__new "
                        "RENAME TO reaction_component"
                    ))

                    # 4. Recreate indexes (canonical set used by ORM).
                    conn.execute(text(
                        "CREATE INDEX ix_reaction_component_reaction_id "
                        "ON reaction_component(reaction_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_reaction_component_substance_id "
                        "ON reaction_component(substance_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_reaction_component_mixture_id "
                        "ON reaction_component(mixture_id)"
                    ))

                    conn.execute(text("PRAGMA foreign_keys=ON"))
                actions.append(
                    "rebuilt reaction_component (substance_id nullable, "
                    "added mixture_id, added XOR check)"
                )
            else:
                actions.append(
                    "reaction_component already migrated — skipped"
                )

        # ── run_component ────────────────────────────────────────
        insp = inspect(engine)
        if "run_component" not in insp.get_table_names():
            actions.append(
                "table run_component absent — db.create_all will create it"
            )
        else:
            needs_rebuild = (
                not _column_is_nullable(insp, "run_component", "substance_id")
                or not _has_column(insp, "run_component", "mixture_id")
            )
            if needs_rebuild:
                with engine.begin() as conn:
                    conn.execute(text("PRAGMA foreign_keys=OFF"))
                    conn.execute(text("""
                        CREATE TABLE run_component__new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            run_id INTEGER NOT NULL REFERENCES run(id),
                            template_component_id INTEGER REFERENCES reaction_component(id),
                            substance_id INTEGER REFERENCES substance(id),
                            mixture_id INTEGER REFERENCES mixture(id),
                            inventory_item_id INTEGER REFERENCES inventory_item(id),
                            role VARCHAR(32) NOT NULL,
                            is_limiting BOOLEAN NOT NULL DEFAULT 0,
                            equivalents FLOAT,
                            concentration_M FLOAT,
                            target_mass_g FLOAT,
                            target_volume_mL FLOAT,
                            actual_mass_g FLOAT,
                            actual_volume_mL FLOAT,
                            position INTEGER NOT NULL DEFAULT 0,
                            CONSTRAINT ck_run_component_substance_xor_mixture
                                CHECK (
                                    (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                                    (CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1
                                )
                        )
                    """))
                    conn.execute(text("""
                        INSERT INTO run_component__new (
                            id, run_id, template_component_id,
                            substance_id, mixture_id, inventory_item_id,
                            role, is_limiting, equivalents, concentration_M,
                            target_mass_g, target_volume_mL,
                            actual_mass_g, actual_volume_mL, position
                        )
                        SELECT
                            id, run_id, template_component_id,
                            substance_id, NULL AS mixture_id, inventory_item_id,
                            role, is_limiting, equivalents, concentration_M,
                            target_mass_g, target_volume_mL,
                            actual_mass_g, actual_volume_mL, position
                        FROM run_component
                    """))
                    conn.execute(text("DROP TABLE run_component"))
                    conn.execute(text(
                        "ALTER TABLE run_component__new RENAME TO run_component"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_run_component_run_id "
                        "ON run_component(run_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_run_component_substance_id "
                        "ON run_component(substance_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_run_component_mixture_id "
                        "ON run_component(mixture_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_run_component_inventory_item_id "
                        "ON run_component(inventory_item_id)"
                    ))
                    conn.execute(text("PRAGMA foreign_keys=ON"))
                actions.append(
                    "rebuilt run_component (substance_id nullable, "
                    "added mixture_id, added XOR check)"
                )
            else:
                actions.append(
                    "run_component already migrated — skipped"
                )

        # Final create_all to pick up anything new.
        db.create_all()

        print("Migration patch 13.5 complete. Actions:")
        for a in actions:
            print(f"  - {a}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
