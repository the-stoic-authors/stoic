"""Stoic ELN — Seed the standard procedure library into an EXISTING db.

``seed_all()`` only runs at ``flask init-db`` / ``scripts/init_db.py``,
so an already-initialised database (a real lab, the dev Mac) needs this
one-shot script to pick up the P2b starter procedures. Idempotent:
re-running skips procedures already present (matched by name).

Run with:  .venv/bin/python scripts/seed_procedures.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.seeds.loader import seed_procedures  # noqa: E402


def main() -> None:
    app = create_app()
    with app.app_context():
        added, skipped = seed_procedures()
        print(f"Procedures: added={added} skipped={skipped}")


if __name__ == "__main__":
    main()
