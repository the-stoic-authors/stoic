"""Stoic ELN — Migration: Settimana 3.5b — user.role column.

Adds a new column to the `user` table:
  - role: VARCHAR(16) NOT NULL DEFAULT 'user'

Retrofits existing users:
  - users with is_admin=True       → role='admin'
  - all other users                → role='user'

Idempotent: safe to re-run, no data loss.

Usage:
    python scripts/migrate_week3_5b.py
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

        if not _has_column(insp, "user", "role"):
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE user ADD COLUMN role VARCHAR(16) "
                    "NOT NULL DEFAULT 'user'"
                ))
            actions.append("Added user.role column (default 'user')")
        else:
            actions.append("user.role already present, skipped")

        # Retrofit: any user with is_admin=True but role='user' → role='admin'.
        with engine.begin() as conn:
            result = conn.execute(text(
                "UPDATE user SET role='admin' WHERE is_admin=1 AND role='user'"
            ))
            n = result.rowcount or 0
            if n > 0:
                actions.append(f"Promoted {n} existing admin(s) to role='admin'")
            else:
                actions.append("No existing admins needed retrofitting")

        for line in actions:
            print(f"  • {line}")
        print("\nMigration complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
