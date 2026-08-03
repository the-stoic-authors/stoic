"""Stoic ELN — Migration: run_step_component 3-way XOR (P2b fix).

P2 added ``free_name``/``free_unit`` to ``run_step_component`` but left
its CHECK constraint at the old 2-way XOR (substance ⊻ mixture = 1).
Its sibling tables (reaction_step_component, step_template_component)
were widened to the 3-way XOR; this one was missed. On any database
created from the model (create_all / ensure-schema) the 2-way CHECK is
present, so launching a Run that contains a free-entry step component
(e.g. a "Colonna Ø" line, or a free eluent) fails at insert time.

SQLite cannot ALTER a CHECK → this rebuilds the table (the patch-13.5
idiom, same as the P2 migration used for the sibling tables). All rows
and FKs are preserved.

Idempotent: skips if the table's CHECK already references ``free_name``.

Run with:
    .venv/bin/python scripts/migrate_p2b_run_step_component_xor.py
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def _check_already_3way(conn) -> bool:
    row = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='run_step_component'")
    ).fetchone()
    if row is None or row[0] is None:
        return False
    # "free_name IS NULL" appears ONLY inside the 3-way CHECK clause —
    # the column itself is declared as "free_name VARCHAR(120)", so the
    # 2-way (unmigrated) schema never contains this exact phrase.
    return "free_name is null" in row[0].lower()


def _rebuild(conn) -> None:
    # Mirrors the canonical model DDL (run_step.py RunStepComponent).
    conn.execute(
        text("""
        CREATE TABLE run_step_component__new (
            id INTEGER NOT NULL PRIMARY KEY,
            step_id INTEGER NOT NULL REFERENCES run_step (id),
            substance_id INTEGER REFERENCES substance (id),
            mixture_id INTEGER REFERENCES mixture (id),
            inventory_item_id INTEGER REFERENCES inventory_item (id),
            free_name VARCHAR(120),
            free_unit VARCHAR(20),
            role VARCHAR(32) NOT NULL,
            ratio_value FLOAT,
            ratio_kind VARCHAR(16),
            target_mass_g FLOAT,
            target_volume_mL FLOAT,
            actual_mass_g FLOAT,
            actual_volume_mL FLOAT,
            position INTEGER NOT NULL,
            CONSTRAINT ck_run_step_component_substance_xor_mixture CHECK (
                (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                (CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) +
                (CASE WHEN free_name IS NULL THEN 0 ELSE 1 END) = 1
            )
        )
        """)
    )
    conn.execute(
        text("""
        INSERT INTO run_step_component__new
            (id, step_id, substance_id, mixture_id, inventory_item_id,
             free_name, free_unit, role, ratio_value, ratio_kind,
             target_mass_g, target_volume_mL, actual_mass_g,
             actual_volume_mL, position)
        SELECT
             id, step_id, substance_id, mixture_id, inventory_item_id,
             free_name, free_unit, role, ratio_value, ratio_kind,
             target_mass_g, target_volume_mL, actual_mass_g,
             actual_volume_mL, position
        FROM run_step_component
        """)
    )
    conn.execute(text("DROP TABLE run_step_component"))
    conn.execute(text("ALTER TABLE run_step_component__new RENAME TO run_step_component"))
    conn.execute(
        text("CREATE INDEX ix_run_step_component_step_id ON run_step_component (step_id)")
    )
    conn.execute(
        text("CREATE INDEX ix_run_step_component_substance_id ON run_step_component (substance_id)")
    )
    conn.execute(
        text("CREATE INDEX ix_run_step_component_mixture_id ON run_step_component (mixture_id)")
    )


def migrate() -> None:
    app = create_app(start_scheduler=False)
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)

        if "run_step_component" not in insp.get_table_names():
            print("run_step_component absent — create_all will create it correctly.")
            db.create_all()
            return

        with engine.begin() as conn:
            if _check_already_3way(conn):
                print("run_step_component already has the 3-way XOR check — skipping.")
                return

            # Ensure the free columns exist before the rebuild copies them
            # (covers a hypothetical pre-P2 database).
            if not _has_column(insp, "run_step_component", "free_name"):
                conn.execute(
                    text("ALTER TABLE run_step_component ADD COLUMN free_name VARCHAR(120)")
                )
            if not _has_column(insp, "run_step_component", "free_unit"):
                conn.execute(
                    text("ALTER TABLE run_step_component ADD COLUMN free_unit VARCHAR(20)")
                )

            conn.execute(text("PRAGMA foreign_keys=OFF"))
            _rebuild(conn)
            conn.execute(text("PRAGMA foreign_keys=ON"))

        print("run_step_component: rebuilt with 3-way XOR (substance ⊻ mixture ⊻ free_name).")


if __name__ == "__main__":
    migrate()
