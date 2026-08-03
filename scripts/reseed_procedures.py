"""Stoic ELN — Re-seed the standard procedure library in English.

The first procedure seeds shipped in Italian. They are now English. This
one-off script removes the old Italian-named seed procedures (and any
English ones already present, so it's safe to re-run) and seeds the
English set.

Safe for protocols: inserting a procedure COPIES it into a reaction, so
deleting the library entry never touches protocols that used it.

Idempotent. Run with:
    .venv/bin/python scripts/reseed_procedures.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from stoic_eln import create_app  # noqa: E402
from stoic_eln.extensions import db  # noqa: E402
from stoic_eln.models.step_template import StepTemplate  # noqa: E402
from stoic_eln.seeds.loader import seed_procedures, seed_substances  # noqa: E402
from stoic_eln.seeds.procedures import PROCEDURES  # noqa: E402

# Names of the original Italian-language seed procedures.
_OLD_IT_NAMES = [
    "Flash facile (ΔRf ≥ 0,3)",
    "Flash media (ΔRf 0,15–0,3)",
    "Flash difficile (ΔRf < 0,15)",
    "Estrazione standard",
    "Ricristallizzazione",
    "Distillazione semplice",
    "Distillazione frazionata",
    "Distillazione sotto vuoto",
]


def main() -> None:
    app = create_app(start_scheduler=False)
    with app.app_context():
        # Delete old IT entries + any English ones already present, so a
        # re-run lands on a clean set.
        targets = set(_OLD_IT_NAMES) | {p["name"] for p in PROCEDURES}
        old = db.session.query(StepTemplate).filter(StepTemplate.name.in_(targets)).all()
        for tpl in old:
            db.session.delete(tpl)  # cascades to components/checklist/parameters
        db.session.commit()
        print(f"Removed {len(old)} existing seed procedure(s).")

        seed_substances()  # idempotent; ensures InChIKey references resolve
        added, skipped = seed_procedures()
        print(f"Procedures: added={added} skipped={skipped}")


if __name__ == "__main__":
    main()
