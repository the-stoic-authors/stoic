"""Stoic ELN — Migration: Settimana 3.5 — template_code + status.

Adds two columns to the `reaction` table:
  - template_code: VARCHAR(20) UNIQUE NULL  — user-chosen mnemonic
  - status: VARCHAR(16) NOT NULL DEFAULT 'published'

Also creates the unique index on template_code.

Idempotent: if a column or index is already present, it is skipped.
Safe to re-run.

Usage:
    python scripts/migrate_week3_5.py
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


def _has_index(insp, table: str, name: str) -> bool:
    if table not in insp.get_table_names():
        return False
    return any(idx["name"] == name for idx in insp.get_indexes(table))


def main() -> None:
    app = create_app()
    with app.app_context():
        insp = inspect(db.engine)
        actions: list[str] = []

        if not insp.get_table_names() or "reaction" not in insp.get_table_names():
            print(
                "ERROR: 'reaction' table not found. Apply Settimana 3 first."
            )
            sys.exit(1)

        # 1. Add template_code column
        if not _has_column(insp, "reaction", "template_code"):
            with db.engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE reaction ADD COLUMN template_code VARCHAR(20)"
                ))
            actions.append("Added column reaction.template_code")
        else:
            actions.append("Skipped: reaction.template_code already present")

        # 2. Add status column
        insp = inspect(db.engine)
        if not _has_column(insp, "reaction", "status"):
            with db.engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE reaction ADD COLUMN status VARCHAR(16) "
                    "NOT NULL DEFAULT 'published'"
                ))
            actions.append("Added column reaction.status")
        else:
            actions.append("Skipped: reaction.status already present")

        # 2b. Add parent_published_id column
        insp = inspect(db.engine)
        if not _has_column(insp, "reaction", "parent_published_id"):
            with db.engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE reaction ADD COLUMN parent_published_id INTEGER "
                    "REFERENCES reaction(id) ON DELETE SET NULL"
                ))
            actions.append("Added column reaction.parent_published_id")
        else:
            actions.append("Skipped: reaction.parent_published_id already present")

        # 3. Create non-unique index on template_code (uniqueness enforced
        #    at application level — drafts can share code with published).
        insp = inspect(db.engine)
        idx_name = "ix_reaction_template_code"
        if not _has_index(insp, "reaction", idx_name):
            with db.engine.begin() as conn:
                conn.execute(text(
                    f"CREATE INDEX {idx_name} "
                    f"ON reaction(template_code)"
                ))
            actions.append(f"Created index {idx_name}")
        else:
            actions.append(f"Skipped: index {idx_name} already present")

        # 4. Create index on status
        idx_status = "ix_reaction_status"
        if not _has_index(insp, "reaction", idx_status):
            with db.engine.begin() as conn:
                conn.execute(text(
                    f"CREATE INDEX {idx_status} ON reaction(status)"
                ))
            actions.append(f"Created index {idx_status}")
        else:
            actions.append(f"Skipped: index {idx_status} already present")

        print("Migration completed:")
        for a in actions:
            print(f"  - {a}")
        print()
        print("You can now restart the app: make run")


if __name__ == "__main__":
    main()
