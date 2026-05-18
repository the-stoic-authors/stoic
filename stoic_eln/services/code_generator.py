"""Stoic ELN — Code generation utilities.

Generates operator codes from full names. Run codes will be added in Week 4.
"""

from __future__ import annotations

import re

from stoic_eln.extensions import db
from stoic_eln.models.user import User


def generate_operator_code(full_name: str) -> str:
    """Derive a 2-3 char operator code from a full name.

    Strategy:
      1. Take the first letter of each word in the name (capitalised).
      2. If less than 2 letters, fall back to the first 2 of the full name.
      3. Append a numeric suffix if a collision exists in the User table.

    Example:
      "Riccardo Di Rosso" -> "RDR"
      "Anna" -> "AN"
      "Anna Bianchi" if exists -> "AB2"
    """
    if not full_name:
        return "USR"

    words = re.findall(r"\w+", full_name)
    if len(words) >= 2:
        base = "".join(w[0].upper() for w in words[:3])
    else:
        base = full_name[:2].upper()

    if not base:
        base = "USR"

    candidate = base
    suffix = 1
    while db.session.query(User).filter_by(operator_code=candidate).first() is not None:
        suffix += 1
        candidate = f"{base}{suffix}"

    return candidate


def generate_reaction_code() -> str:
    """Generate the next reaction code in the format 'RX-YYYY-NNNN'.

    Sequence is per-year: the first reaction of 2026 is RX-2026-0001, the
    second is RX-2026-0002, etc. Sequence resets each year.

    Strategy: query the highest existing code matching the current year prefix,
    parse the trailing 4-digit number, increment, and zero-pad.
    """
    from datetime import date

    from stoic_eln.models.reaction import Reaction

    year = date.today().year
    prefix = f"RX-{year}-"

    last = (
        db.session.query(Reaction)
        .filter(Reaction.code.like(f"{prefix}%"))
        .order_by(Reaction.code.desc())
        .first()
    )

    if last is None:
        seq = 1
    else:
        try:
            seq = int(last.code.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1

    return f"{prefix}{seq:04d}"
