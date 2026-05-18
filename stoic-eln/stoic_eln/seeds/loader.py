"""Stoic ELN — Seed loader.

Idempotent loaders: re-running them is safe and skips already-present rows.
"""

from __future__ import annotations

import logging

from stoic_eln.extensions import db
from stoic_eln.models.hazard_phrase import HazardPhrase
from stoic_eln.models.substance import Substance
from stoic_eln.seeds.hazard_phrases import HAZARD_PHRASES
from stoic_eln.seeds.substances import SUBSTANCES

logger = logging.getLogger(__name__)


def seed_hazard_phrases() -> tuple[int, int]:
    """Insert official ECHA H/P phrase texts.

    Returns (added, skipped).
    """
    added = 0
    skipped = 0
    for code, category, en, it in HAZARD_PHRASES:
        existing = db.session.get(HazardPhrase, code)
        if existing is None:
            db.session.add(
                HazardPhrase(code=code, category=category, text_en=en, text_it=it)
            )
            added += 1
        else:
            skipped += 1
    db.session.commit()
    logger.info("Hazard phrases: added=%d skipped=%d", added, skipped)
    return added, skipped


def seed_substances() -> tuple[int, int]:
    """Insert starter substance catalogue.

    Skips substances whose InChIKey already exists. Returns (added, skipped).
    """
    added = 0
    skipped = 0
    for entry in SUBSTANCES:
        inchi_key = entry.get("inchi_key")
        if inchi_key:
            existing = db.session.query(Substance).filter_by(inchi_key=inchi_key).first()
            if existing:
                skipped += 1
                continue
        sub = Substance(**entry)
        db.session.add(sub)
        added += 1
    db.session.commit()
    logger.info("Substances: added=%d skipped=%d", added, skipped)
    return added, skipped


def seed_all() -> dict[str, tuple[int, int]]:
    """Run all seeders. Safe to call multiple times."""
    return {
        "hazard_phrases": seed_hazard_phrases(),
        "substances": seed_substances(),
    }
