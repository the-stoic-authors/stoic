"""Stoic ELN — Migration: Settimana 6 patch 13.6 — Step components
support Mixtures.

Mirrors patch 13.5's schema changes but for the *step*-level tables:
``reaction_step_component`` and ``run_step_component``. Both gain an
optional ``mixture_id`` FK, lose the NOT NULL on ``substance_id``, and
acquire an XOR CHECK constraint.

Idempotent. Uses the same SQLite table-rebuild idiom as 13.0/13.5.
Existing rows preserve ``substance_id`` and end up with
``mixture_id=NULL`` — satisfies the XOR.
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

        # ── reaction_step_component ──────────────────────────────
        if "reaction_step_component" not in insp.get_table_names():
            actions.append(
                "table reaction_step_component absent — db.create_all will create it"
            )
        else:
            needs_rebuild = (
                not _column_is_nullable(insp, "reaction_step_component", "substance_id")
                or not _has_column(insp, "reaction_step_component", "mixture_id")
            )
            if needs_rebuild:
                with engine.begin() as conn:
                    conn.execute(text("PRAGMA foreign_keys=OFF"))
                    conn.execute(text("""
                        CREATE TABLE reaction_step_component__new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            step_id INTEGER NOT NULL
                                REFERENCES reaction_step(id) ON DELETE CASCADE,
                            substance_id INTEGER REFERENCES substance(id),
                            mixture_id INTEGER REFERENCES mixture(id),
                            position INTEGER NOT NULL DEFAULT 0,
                            role VARCHAR(40) NOT NULL DEFAULT 'solvent',
                            ratio_kind VARCHAR(20) NOT NULL DEFAULT 'eq',
                            ratio_value FLOAT,
                            concentration_M FLOAT,
                            notes TEXT,
                            created_at DATETIME NOT NULL,
                            CONSTRAINT ck_reaction_step_component_substance_xor_mixture
                                CHECK (
                                    (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                                    (CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1
                                )
                        )
                    """))
                    conn.execute(text("""
                        INSERT INTO reaction_step_component__new (
                            id, step_id, substance_id, mixture_id,
                            position, role, ratio_kind, ratio_value,
                            concentration_M, notes, created_at
                        )
                        SELECT
                            id, step_id, substance_id, NULL AS mixture_id,
                            position, role, ratio_kind, ratio_value,
                            concentration_M, notes, created_at
                        FROM reaction_step_component
                    """))
                    conn.execute(text("DROP TABLE reaction_step_component"))
                    conn.execute(text(
                        "ALTER TABLE reaction_step_component__new "
                        "RENAME TO reaction_step_component"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_reaction_step_component_step_id "
                        "ON reaction_step_component(step_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_reaction_step_component_substance_id "
                        "ON reaction_step_component(substance_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_reaction_step_component_mixture_id "
                        "ON reaction_step_component(mixture_id)"
                    ))
                    conn.execute(text("PRAGMA foreign_keys=ON"))
                actions.append(
                    "rebuilt reaction_step_component "
                    "(substance_id nullable, added mixture_id, added XOR check)"
                )
            else:
                actions.append(
                    "reaction_step_component already migrated — skipped"
                )

        # ── run_step_component ──────────────────────────────────
        insp = inspect(engine)
        if "run_step_component" not in insp.get_table_names():
            actions.append(
                "table run_step_component absent — db.create_all will create it"
            )
        else:
            needs_rebuild = (
                not _column_is_nullable(insp, "run_step_component", "substance_id")
                or not _has_column(insp, "run_step_component", "mixture_id")
            )
            if needs_rebuild:
                with engine.begin() as conn:
                    conn.execute(text("PRAGMA foreign_keys=OFF"))
                    conn.execute(text("""
                        CREATE TABLE run_step_component__new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            step_id INTEGER NOT NULL REFERENCES run_step(id),
                            substance_id INTEGER REFERENCES substance(id),
                            mixture_id INTEGER REFERENCES mixture(id),
                            inventory_item_id INTEGER REFERENCES inventory_item(id),
                            role VARCHAR(32) NOT NULL,
                            ratio_value FLOAT,
                            ratio_kind VARCHAR(16),
                            target_mass_g FLOAT,
                            target_volume_mL FLOAT,
                            actual_mass_g FLOAT,
                            actual_volume_mL FLOAT,
                            position INTEGER NOT NULL DEFAULT 0,
                            CONSTRAINT ck_run_step_component_substance_xor_mixture
                                CHECK (
                                    (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                                    (CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1
                                )
                        )
                    """))
                    conn.execute(text("""
                        INSERT INTO run_step_component__new (
                            id, step_id, substance_id, mixture_id,
                            inventory_item_id, role, ratio_value, ratio_kind,
                            target_mass_g, target_volume_mL,
                            actual_mass_g, actual_volume_mL, position
                        )
                        SELECT
                            id, step_id, substance_id, NULL AS mixture_id,
                            inventory_item_id, role, ratio_value, ratio_kind,
                            target_mass_g, target_volume_mL,
                            actual_mass_g, actual_volume_mL, position
                        FROM run_step_component
                    """))
                    conn.execute(text("DROP TABLE run_step_component"))
                    conn.execute(text(
                        "ALTER TABLE run_step_component__new "
                        "RENAME TO run_step_component"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_run_step_component_step_id "
                        "ON run_step_component(step_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_run_step_component_substance_id "
                        "ON run_step_component(substance_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX ix_run_step_component_mixture_id "
                        "ON run_step_component(mixture_id)"
                    ))
                    conn.execute(text("PRAGMA foreign_keys=ON"))
                actions.append(
                    "rebuilt run_step_component "
                    "(substance_id nullable, added mixture_id, added XOR check)"
                )
            else:
                actions.append(
                    "run_step_component already migrated — skipped"
                )

        db.create_all()

        print("Migration patch 13.6 complete. Actions:")
        for a in actions:
            print(f"  - {a}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
