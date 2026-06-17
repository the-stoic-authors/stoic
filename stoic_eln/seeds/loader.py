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
            db.session.add(HazardPhrase(code=code, category=category, text_en=en, text_it=it))
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


def seed_procedures() -> tuple[int, int]:
    """Insert the standard procedure library (P2b).

    Idempotent by StepTemplate.name: a procedure a lab deleted stays
    gone. Components referencing a substance are resolved by InChIKey
    against the (already seeded) substance catalogue; a missing
    substance skips just that component, with a warning. Returns
    (added, skipped) counted per procedure.
    """
    from stoic_eln.models.step_template import (
        StepTemplate,
        StepTemplateChecklistItem,
        StepTemplateComponent,
        StepTemplateParameter,
    )
    from stoic_eln.seeds.procedures import PROCEDURES

    added = 0
    skipped = 0
    for proc in PROCEDURES:
        existing = db.session.query(StepTemplate).filter_by(name=proc["name"]).first()
        if existing is not None:
            skipped += 1
            continue

        tpl = StepTemplate(
            name=proc["name"],
            kind=proc.get("kind", "workup"),
            description=proc.get("description"),
        )

        for pos, comp in enumerate(proc.get("components", [])):
            substance_id = None
            inchikey = comp.get("substance_inchikey")
            if inchikey:
                sub = db.session.query(Substance).filter_by(inchi_key=inchikey).first()
                if sub is None:
                    logger.warning(
                        "Procedure %r references missing substance %s — skipping that component",
                        proc["name"],
                        inchikey,
                    )
                    continue
                substance_id = sub.id

            tpl.components.append(
                StepTemplateComponent(
                    substance_id=substance_id,
                    free_name=comp.get("free_name"),
                    free_unit=comp.get("free_unit"),
                    role=comp.get("role", "solvent"),
                    ratio_kind=comp.get("ratio_kind", "eq"),
                    ratio_value=comp.get("ratio_value"),
                    position=pos,
                )
            )

        for pos, item_text in enumerate(proc.get("checklist", [])):
            tpl.checklist_items.append(StepTemplateChecklistItem(text=item_text, position=pos))

        for pos, prm in enumerate(proc.get("parameters", [])):
            tpl.parameters.append(
                StepTemplateParameter(
                    label=prm["label"],
                    unit=prm.get("unit"),
                    position=pos,
                )
            )

        db.session.add(tpl)
        added += 1

    db.session.commit()
    logger.info("Procedures: added=%d skipped=%d", added, skipped)
    return added, skipped


def seed_all() -> dict[str, tuple[int, int]]:
    """Run all seeders. Safe to call multiple times."""
    return {
        "hazard_phrases": seed_hazard_phrases(),
        "substances": seed_substances(),
        # Procedures depend on substances (resolved by InChIKey), so
        # they must run after seed_substances().
        "procedures": seed_procedures(),
    }
