"""Regression: editing/publishing a protocol with a free-entry step component.

A column-diameter (or any free-entry) step component has no substance and no
mixture — only ``free_name``. ``clone_for_editing`` (Edit) and ``promote_draft``
(Publish) used to drop ``free_name``/``free_unit`` (and, in promote, also
mixture/concentration/notes), producing a component with none of the XOR fields
set → CHECK constraint failure. These tests lock the faithful copy.
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models import Reaction, ReactionStep, ReactionStepComponent
from stoic_eln.services.reaction_clone import clone_for_editing, promote_draft


def _published_with_free_component() -> int:
    rxn = Reaction(
        code="RX-2026-CLONEFREE",
        title="clone free",
        status="published",
        template_code="MDCLONE.1",
        template_code_base="MDCLONE",
        version_number=1,
    )
    db.session.add(rxn)
    db.session.flush()
    step = ReactionStep(reaction_id=rxn.id, position=0, kind="purification", title="Flash")
    db.session.add(step)
    db.session.flush()
    db.session.add(
        ReactionStepComponent(
            step_id=step.id,
            role="additive",
            free_name="Column Ø",
            free_unit="mm",
            ratio_kind="column_diameter_mm",
            ratio_value=15.0,
            position=1,
        )
    )
    db.session.commit()
    return rxn.id


def test_clone_for_editing_preserves_free_entry(app):
    with app.app_context():
        rid = _published_with_free_component()
        rxn = db.session.get(Reaction, rid)
        draft = clone_for_editing(rxn, created_by_id=None)
        comps = [
            (c.free_name, c.free_unit, c.ratio_kind, c.substance_id, c.mixture_id)
            for s in draft.steps
            for c in s.components
        ]
        assert comps == [("Column Ø", "mm", "column_diameter_mm", None, None)]


def test_promote_draft_preserves_free_entry(app):
    with app.app_context():
        rid = _published_with_free_component()
        rxn = db.session.get(Reaction, rid)
        draft = clone_for_editing(rxn, created_by_id=None)
        published = promote_draft(draft)
        comps = [
            (c.free_name, c.free_unit, c.ratio_kind) for s in published.steps for c in s.components
        ]
        assert comps == [("Column Ø", "mm", "column_diameter_mm")]
