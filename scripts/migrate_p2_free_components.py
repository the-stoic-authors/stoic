"""Stoic ELN — Migration: P2 free-entry step components.

Schema changes:
  1. ``reaction_step_component``: add ``free_name``, ``free_unit``;
     widen the XOR check to substance ⊻ mixture ⊻ free_name.
  2. ``step_template_component``: same.
  3. ``run_step_component``: add ``free_name``, ``free_unit``
     (plain ADD COLUMN — that table carries no XOR check).

Tables 1-2 carry a CHECK constraint that must change, and SQLite
cannot ALTER a CHECK — so they use the table-rebuild idiom from
patch 13.5. Idempotent: presence of ``free_name`` is the marker.

Run with:  .venv/bin/python scripts/migrate_p2_free_components.py
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def _rebuild_with_free(conn, table: str, fk_parent: str, check_name: str) -> None:
    """Rebuild `table` adding free_name/free_unit + 3-way XOR check.

    fk_parent: the FK target of the *_id parent column
        (reaction_step.id or step_template.id).
    """
    parent_col = "step_id" if table == "reaction_step_component" else "template_id"
    # reaction_step_component has created_at; step_template_component
    # (born in P1) does not. The DDL and the column lists must match
    # the real model schemas exactly.
    has_created = table == "reaction_step_component"
    created_at_ddl = "created_at DATETIME NOT NULL," if has_created else ""
    created_cols = ", created_at" if has_created else ""
    tmp = f"{table}__new"

    conn.execute(
        text(f"""
        CREATE TABLE {tmp} (
            id INTEGER NOT NULL PRIMARY KEY,
            {parent_col} INTEGER NOT NULL REFERENCES {fk_parent} ON DELETE CASCADE,
            substance_id INTEGER REFERENCES substance (id),
            mixture_id INTEGER REFERENCES mixture (id),
            free_name VARCHAR(120),
            free_unit VARCHAR(20),
            position INTEGER NOT NULL,
            role VARCHAR(40) NOT NULL,
            ratio_kind VARCHAR(20) NOT NULL,
            ratio_value FLOAT,
            concentration_M FLOAT,
            notes TEXT,
            {created_at_ddl}
            CONSTRAINT {check_name} CHECK (
                (CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) +
                (CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) +
                (CASE WHEN free_name IS NULL THEN 0 ELSE 1 END) = 1
            )
        )
        """)
    )
    conn.execute(
        text(f"""
        INSERT INTO {tmp}
            (id, {parent_col}, substance_id, mixture_id, free_name, free_unit,
             position, role, ratio_kind, ratio_value, concentration_M, notes{created_cols})
        SELECT id, {parent_col}, substance_id, mixture_id, NULL, NULL,
               position, role, ratio_kind, ratio_value, concentration_M, notes{created_cols}
        FROM {table}
        """)
    )
    conn.execute(text(f"DROP TABLE {table}"))
    conn.execute(text(f"ALTER TABLE {tmp} RENAME TO {table}"))
    conn.execute(text(f"CREATE INDEX ix_{table}_{parent_col} ON {table} ({parent_col})"))
    conn.execute(text(f"CREATE INDEX ix_{table}_substance_id ON {table} (substance_id)"))
    conn.execute(text(f"CREATE INDEX ix_{table}_mixture_id ON {table} (mixture_id)"))


def main() -> int:
    app = create_app(start_scheduler=False)
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        actions: list[str] = []
        tables = insp.get_table_names()

        # 1-2: rebuilds (CHECK change)
        for table, parent, check in (
            (
                "reaction_step_component",
                "reaction_step (id)",
                "ck_reaction_step_component_substance_xor_mixture",
            ),
            (
                "step_template_component",
                "step_template (id)",
                "ck_step_template_component_substance_xor_mixture",
            ),
        ):
            if table not in tables:
                actions.append(f"{table}: absent — create_all will create it fresh")
                continue
            if _has_column(insp, table, "free_name"):
                actions.append(f"{table}: already migrated")
                continue
            with engine.begin() as conn:
                conn.execute(text("PRAGMA foreign_keys=OFF"))
                _rebuild_with_free(conn, table, parent, check)
                conn.execute(text("PRAGMA foreign_keys=ON"))
            actions.append(f"{table}: rebuilt with free_name/free_unit + 3-way XOR")

        # 3: plain column adds (no check on run_step_component)
        if "run_step_component" in tables:
            if _has_column(insp, "run_step_component", "free_name"):
                actions.append("run_step_component: already migrated")
            else:
                with engine.begin() as conn:
                    conn.execute(
                        text("ALTER TABLE run_step_component ADD COLUMN free_name VARCHAR(120)")
                    )
                    conn.execute(
                        text("ALTER TABLE run_step_component ADD COLUMN free_unit VARCHAR(20)")
                    )
                actions.append("run_step_component: free_name/free_unit added")
        else:
            actions.append("run_step_component: absent — create_all will create it")

        db.create_all()

        print("Migration P2 free components:")
        for a in actions:
            print(f"  - {a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
