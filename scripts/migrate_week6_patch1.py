"""Stoic ELN — Migration: Settimana 6 patch 1 — Groups.

Creates two new tables and adds two new columns:

  - new table ``group`` (id, slug, name, description, is_default, is_active, created_at)
  - new table ``group_membership`` (id, user_id, group_id, role, joined_at)
  - new column ``user.default_group_id`` (FK group.id, nullable)
  - new column ``inventory_item.group_id`` (FK group.id, NOT NULL after backfill)

Backfills:
  - Creates a ``Default`` group (slug='default', is_default=True)
  - Adds every existing user as a member with role='member'
  - Sets every user's ``default_group_id`` to the Default group
  - Assigns every existing inventory_item to the Default group

Idempotent: safe to re-run.
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, column: str) -> bool:
    if not _has_table(insp, table):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def main() -> int:
    app = create_app()
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        actions: list[str] = []

        # 1) Create `group` table
        if not _has_table(insp, "group"):
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE "group" (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        slug VARCHAR(64) NOT NULL UNIQUE,
                        name VARCHAR(120) NOT NULL,
                        description VARCHAR(500),
                        is_default BOOLEAN NOT NULL DEFAULT 0,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text(
                    'CREATE INDEX ix_group_slug ON "group"(slug)'
                ))
                conn.execute(text(
                    "CREATE INDEX ix_group_is_default "
                    'ON "group"(is_default)'
                ))
            insp = inspect(engine)
            actions.append("Created table 'group'")
        else:
            actions.append("Table 'group' already present, skipped")

        # 2) Create the Default group (only if no rows exist yet)
        with engine.begin() as conn:
            count = conn.execute(text(
                'SELECT COUNT(*) FROM "group"'
            )).scalar()
            if not count:
                conn.execute(text("""
                    INSERT INTO "group" (slug, name, description, is_default, is_active)
                    VALUES ('default', 'Default',
                            'Gruppo di default del laboratorio.', 1, 1)
                """))
                actions.append("Created 'Default' group")
            else:
                actions.append(f"Found {count} existing groups, skipped Default creation")

            default_group_id = conn.execute(text(
                'SELECT id FROM "group" WHERE slug = :s'
            ), {"s": "default"}).scalar()

        # 3) Create `group_membership` table
        if not _has_table(insp, "group_membership"):
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE group_membership (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
                        group_id INTEGER NOT NULL REFERENCES "group"(id) ON DELETE CASCADE,
                        role VARCHAR(16) NOT NULL DEFAULT 'member',
                        joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, group_id)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_group_membership_user "
                    "ON group_membership(user_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_group_membership_group "
                    "ON group_membership(group_id)"
                ))
            insp = inspect(engine)
            actions.append("Created table 'group_membership'")
        else:
            actions.append("Table 'group_membership' already present, skipped")

        # 4) Add `user.default_group_id`
        if not _has_column(insp, "user", "default_group_id"):
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE user ADD COLUMN "
                    "default_group_id INTEGER REFERENCES \"group\"(id)"
                ))
            actions.append("Added user.default_group_id")
        else:
            actions.append("user.default_group_id already present, skipped")

        # 5) Add `inventory_item.group_id`
        # Two-phase: add nullable, backfill, then enforce NOT NULL via a
        # CHECK (SQLite won't easily ALTER NOT NULL).
        if not _has_column(insp, "inventory_item", "group_id"):
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE inventory_item ADD COLUMN "
                    "group_id INTEGER REFERENCES \"group\"(id)"
                ))
            actions.append("Added inventory_item.group_id (nullable)")
        else:
            actions.append("inventory_item.group_id already present, skipped")

        # 6) Backfill memberships, default_group, and inventory_item.group_id
        with engine.begin() as conn:
            # Add every user to the Default group (if not already)
            users = conn.execute(text("SELECT id FROM user")).fetchall()
            n_added = 0
            for row in users:
                exists = conn.execute(text(
                    "SELECT 1 FROM group_membership "
                    "WHERE user_id = :u AND group_id = :g"
                ), {"u": row.id, "g": default_group_id}).first()
                if not exists:
                    conn.execute(text(
                        "INSERT INTO group_membership (user_id, group_id, role) "
                        "VALUES (:u, :g, 'member')"
                    ), {"u": row.id, "g": default_group_id})
                    n_added += 1
            actions.append(
                f"Added {n_added} users to Default group "
                f"(of {len(users)} total)"
            )

            # Set default_group_id on users without one
            updated = conn.execute(text(
                "UPDATE user SET default_group_id = :g "
                "WHERE default_group_id IS NULL"
            ), {"g": default_group_id})
            actions.append(
                f"Set default_group_id on {updated.rowcount} users"
            )

            # Backfill inventory_item.group_id where NULL
            updated = conn.execute(text(
                "UPDATE inventory_item SET group_id = :g "
                "WHERE group_id IS NULL"
            ), {"g": default_group_id})
            actions.append(
                f"Backfilled group_id on {updated.rowcount} inventory items"
            )

        for line in actions:
            print(f"  • {line}")
        print("\nMigration complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
