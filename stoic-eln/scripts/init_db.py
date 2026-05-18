"""Initialize the Stoic ELN database.

Creates schema, admin user, and seed data (hazard phrases + starter substances).

Usage:
    python scripts/init_db.py
    python scripts/init_db.py --admin-password mypass --reset
    python scripts/init_db.py --no-seed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stoic_eln import create_app
from stoic_eln.extensions import db
from stoic_eln.models.user import User
from stoic_eln.seeds.loader import seed_all
from stoic_eln.services.audit import log_event


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize Stoic ELN database.")
    parser.add_argument("--admin-password", default="admin123", help="Admin password")
    parser.add_argument("--reset", action="store_true", help="Drop existing tables first")
    parser.add_argument("--no-seed", action="store_true", help="Skip seed data")
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        if args.reset:
            print("Dropping all tables...")
            db.drop_all()

        print("Creating tables...")
        db.create_all()

        existing = db.session.query(User).filter_by(username="admin").first()
        if existing is None:
            admin = User(
                username="admin",
                full_name="Amministratore",
                operator_code="ADM",
                is_admin=True,
                is_active=True,
                locale="it",
            )
            admin.set_password(args.admin_password)
            db.session.add(admin)
            db.session.commit()
            log_event(action="create", entity_type="user", entity_id=admin.id, user_id=None)
            print(f"Admin user created: admin / {args.admin_password}")
            print("Change this password immediately after first login!")
        else:
            print("Admin user already exists.")

        if not args.no_seed:
            print()
            print("Loading seed data...")
            results = seed_all()
            for label, (added, skipped) in results.items():
                print(f"  {label}: added={added} skipped={skipped}")

        print()
        print("Done. Run the app with: flask --app stoic_eln run --debug")
        return 0


if __name__ == "__main__":
    sys.exit(main())
