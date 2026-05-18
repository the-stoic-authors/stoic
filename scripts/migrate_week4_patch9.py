"""Stoic ELN — Migration: Settimana 4 patch 9 — Reaction versioning.

Adds 4 new columns to the ``reaction`` table:
  - template_code_base : VARCHAR(20)  (family code, no version suffix)
  - version_number     : INTEGER NOT NULL DEFAULT 1
  - parent_version_id  : INTEGER NULL (FK to reaction.id)
  - is_archived        : BOOLEAN NOT NULL DEFAULT 0

Also backfills:
  - For published reactions whose ``template_code`` does NOT contain '.':
    (i.e. legacy data without versioning), set
      template_code_base = template_code
      template_code = template_code + ".1"
      version_number = 1
  - For published reactions whose ``template_code`` already contains '.':
    treat what's after the dot as version_number, what's before as base.

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
    cols = {c["name"] for c in insp.get_columns(table)}
    return column in cols


def main() -> int:
    app = create_app()
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)

        actions: list[str] = []

        # Add columns if missing
        col_specs = [
            ("template_code_base", "VARCHAR(20)"),
            ("version_number", "INTEGER NOT NULL DEFAULT 1"),
            ("parent_version_id", "INTEGER"),
            ("is_archived", "BOOLEAN NOT NULL DEFAULT 0"),
        ]
        for col_name, col_def in col_specs:
            if not _has_column(insp, "reaction", col_name):
                with engine.begin() as conn:
                    conn.execute(text(
                        f"ALTER TABLE reaction ADD COLUMN {col_name} {col_def}"
                    ))
                actions.append(f"Added reaction.{col_name}")
            else:
                actions.append(f"reaction.{col_name} already present, skipped")

        # Backfill template_code_base + version_number for published rows.
        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, template_code FROM reaction "
                "WHERE status='published' AND template_code IS NOT NULL "
                "AND (template_code_base IS NULL OR template_code_base = '')"
            )).fetchall()
            for row in rows:
                rid, tc = row.id, row.template_code
                if "." in tc:
                    base, _, ver = tc.rpartition(".")
                    try:
                        ver_num = int(ver)
                    except ValueError:
                        base, ver_num = tc, 1
                else:
                    base = tc
                    ver_num = 1
                    # Promote legacy code to versioned form
                    new_tc = f"{tc}.1"
                    conn.execute(text(
                        "UPDATE reaction SET template_code_base = :b, "
                        "version_number = :v, template_code = :new_tc "
                        "WHERE id = :rid"
                    ), {"b": base, "v": ver_num, "new_tc": new_tc, "rid": rid})
                    # Update any Run snapshots that reference the old code
                    conn.execute(text(
                        "UPDATE run SET template_code_snapshot = :new_tc "
                        "WHERE reaction_id = :rid AND template_code_snapshot = :old_tc"
                    ), {"new_tc": new_tc, "rid": rid, "old_tc": tc})
                    continue

                conn.execute(text(
                    "UPDATE reaction SET template_code_base = :b, "
                    "version_number = :v WHERE id = :rid"
                ), {"b": base, "v": ver_num, "rid": rid})
            actions.append(f"Backfilled {len(rows)} published reactions.")

        for line in actions:
            print(f"  • {line}")
        print("\nMigration complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
