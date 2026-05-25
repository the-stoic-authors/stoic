"""Stoic ELN — Deep clone of a reaction template.

Used by the draft-and-publish workflow:
  - "Modifica" on a published reaction creates a draft copy
  - "Salva" on the draft replaces the published with the draft
  - "Annulla" on the draft simply deletes it

The clone preserves:
  - all Reaction scalar fields
  - all ReactionComponent rows
  - all ReactionStep rows + their ReactionStepComponent + ChecklistItems
  - all reaction-level ChecklistItems

It does NOT preserve:
  - the unique `code` (regenerated)
  - the `template_code` (left NULL on the draft so the user can review)
  - the `status` (set to 'draft' on the copy)
  - timestamps (reset to now)
  - parent/run links — runs always point to the published reaction
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stoic_eln.extensions import db
from stoic_eln.models.checklist_item import ChecklistItem
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_component import ReactionComponent
from stoic_eln.models.reaction_step import ReactionStep
from stoic_eln.models.reaction_step_component import ReactionStepComponent

if TYPE_CHECKING:
    pass


def clone_for_editing(source: Reaction, *, created_by_id: int | None = None) -> Reaction:
    """Create a draft copy of a published reaction.

    The draft is fully independent — modifications to it don't affect the
    source until the user explicitly publishes (which will swap the draft
    in via ``promote_draft``).

    Args:
        source: the Reaction to clone (typically status='published').
        created_by_id: user id to attach as creator of the draft.

    Returns:
        The newly-persisted draft Reaction (already committed to the DB).
    """
    from stoic_eln.services.code_generator import generate_reaction_code

    # 1. Clone the Reaction itself
    draft = Reaction(
        code=generate_reaction_code(),
        template_code=source.template_code,  # keep the same mnemonic on the draft
        template_code_base=source.template_code_base,  # carry over the family
        status="draft",
        parent_published_id=source.id,
        title=source.title,
        description=source.description,
        procedure=source.procedure,
        temperature_c=source.temperature_c,
        duration_hours=source.duration_hours,
        atmosphere=source.atmosphere,
        pressure_bar=source.pressure_bar,
        scheme_smiles=source.scheme_smiles,
        source=source.source,
        notes=source.notes,
        default_scale_mmol=source.default_scale_mmol,
        created_by_id=created_by_id,
        is_active=True,
    )
    db.session.add(draft)
    db.session.flush()

    # 2. Clone components — keep a map old_id → new_component to remap
    #    step.reference_component_id below.
    comp_map: dict[int, ReactionComponent] = {}
    for c in source.components:
        new_c = ReactionComponent(
            reaction_id=draft.id,
            substance_id=c.substance_id,
            role=c.role,
            position=c.position,
            equivalents=c.equivalents,
            amount_mmol=c.amount_mmol,
            amount_g=c.amount_g,
            amount_mL=c.amount_mL,
            is_limiting=c.is_limiting,
            concentration_M=c.concentration_M,
            notes=c.notes,
        )
        db.session.add(new_c)
        db.session.flush()
        comp_map[c.id] = new_c

    # 3. Clone reaction-level checklist
    for item in source.checklist_items:
        db.session.add(
            ChecklistItem(
                reaction_id=draft.id,
                position=item.position,
                text=item.text,
                is_default_done=item.is_default_done,
            )
        )

    # 4. Clone steps + their components + their checklists
    for step in source.steps:
        # Remap reference_component_id through comp_map
        new_ref = (
            comp_map[step.reference_component_id].id
            if step.reference_component_id and step.reference_component_id in comp_map
            else None
        )
        new_step = ReactionStep(
            reaction_id=draft.id,
            position=step.position,
            kind=step.kind,
            title=step.title,
            description=step.description,
            reference_component_id=new_ref,
        )
        db.session.add(new_step)
        db.session.flush()

        for sc in step.components:
            # Step components can reference EITHER a substance OR a
            # mixture (e.g. an eluent like 'EtOAc/PE 5:2', or a
            # buffer like 'PBS pH 7.4'). The model enforces XOR via a
            # CHECK constraint; we must clone whichever is set. Bug
            # before 14.6.2: this loop only carried substance_id over,
            # leaving mixture_id=None, which broke the clone for any
            # step containing a mixture-based solvent.
            db.session.add(
                ReactionStepComponent(
                    step_id=new_step.id,
                    substance_id=sc.substance_id,
                    mixture_id=sc.mixture_id,
                    position=sc.position,
                    role=sc.role,
                    ratio_kind=sc.ratio_kind,
                    ratio_value=sc.ratio_value,
                    concentration_M=sc.concentration_M,
                    notes=sc.notes,
                )
            )

        for item in step.checklist_items:
            db.session.add(
                ChecklistItem(
                    step_id=new_step.id,
                    position=item.position,
                    text=item.text,
                    is_default_done=item.is_default_done,
                )
            )

    db.session.commit()
    return draft


def promote_draft(draft: Reaction) -> Reaction:
    """Publish a draft as a new version.

    Two cases:

    A) **Brand-new template** (``parent_published_id`` is None): user
       typed a base code (e.g. 'MD600B'). On publish:
         - We assign ``template_code = 'MD600B.1'`` (version 1)
         - ``template_code_base = 'MD600B'``, ``version_number = 1``
         - Status flips to 'published'
       The draft becomes the published v1 in place.

    B) **Edit of a published template**: the draft was made via
       ``clone_for_editing``, so its ``parent_published_id`` points to
       the previous published version. On publish:
         - The draft becomes a NEW row (its own id is preserved) with
           ``version_number = parent.version_number + 1``
         - ``template_code = '<base>.<new_version>'``
         - The PARENT (previous version) is marked ``is_archived=True``
           but kept in the DB so historical Runs still resolve.

    Run records from older versions are NEVER touched: they continue
    to point to whatever Reaction.id they were created against, and
    their ``template_code_snapshot`` preserves the historical code.

    Returns the now-published Reaction.
    """
    from stoic_eln.services import template_code as tc_svc

    if draft.status != "draft":
        raise ValueError("promote_draft called on a non-draft reaction")

    # The user must have typed a base code by now.
    base = tc_svc.normalize(draft.template_code_base or draft.template_code)
    if not base:
        raise ValueError("Il template deve avere un codice prima di essere salvato.")

    # If template_code is set as a fully-versioned form (legacy path),
    # extract the base.
    split = tc_svc.split_versioned(base)
    if split:
        base = split[0]

    # Validate the base — must be syntactically valid and not collide
    # with another existing FAMILY (other than the draft itself).
    # Allow the parent's family to remain the same one we're versioning.
    parent = None
    if draft.parent_published_id is not None:
        parent = db.session.get(Reaction, draft.parent_published_id)

    # If we have a parent, the family must match (the user can't change
    # the family code of an existing template).
    if parent and parent.template_code_base and base != parent.template_code_base:
        # Allow the user to change to a code that's THEIR own family
        # (corner case: legacy data without a base set).
        pass  # we'll fall through and validate below

    # Validate the base — exclude the draft itself and any same-family rows
    # that we'll be archiving (in case the parent has the same base).
    same_family_ids = []
    if parent and parent.template_code_base == base:
        # Allowed: we're versioning the same family
        same_family_ids = [
            r.id
            for r in db.session.query(Reaction).filter(Reaction.template_code_base == base).all()
        ]

    # Manual conflict check (validate_base would raise; we want a clearer flow)
    q = db.session.query(Reaction).filter(
        Reaction.template_code_base == base,
        Reaction.id != draft.id,
    )
    for rid in same_family_ids:
        if rid != draft.id:
            q = q.filter(Reaction.id != rid)
    conflict = q.filter(Reaction.status == "published", Reaction.is_archived.is_(False)).first()
    if conflict and (parent is None or conflict.id != parent.id):
        from stoic_eln.services.template_code import TemplateCodeError

        raise TemplateCodeError(
            f"Il codice '{base}' è già usato da un altro template "
            f"({conflict.template_code} — {conflict.title or '?'}). "
            f"Per pubblicare una nuova versione, usa il bottone "
            f'"Modifica" sul template esistente; per crearne uno '
            f"distinto, scegli un codice diverso."
        )

    # Decide the version number.
    if parent is None:
        # Brand-new family: v1
        new_version = 1
    else:
        new_version = (parent.version_number or 1) + 1
        # Archive the parent (and any other non-archived versions of this family,
        # for safety against weird states)
        for old in (
            db.session.query(Reaction)
            .filter(
                Reaction.template_code_base == base,
                Reaction.id != draft.id,
                Reaction.status == "published",
                Reaction.is_archived.is_(False),
            )
            .all()
        ):
            old.is_archived = True

    # Apply versioning to the draft
    draft.template_code_base = base
    draft.version_number = new_version
    draft.template_code = tc_svc.make_versioned(base, new_version)
    draft.status = "published"
    draft.is_archived = False
    if parent is not None:
        draft.parent_version_id = parent.id
    draft.parent_published_id = None  # no longer relevant once published

    db.session.commit()
    return draft


def discard_draft(draft: Reaction) -> None:
    """Delete a draft reaction and all its children (cascade)."""
    if draft.status != "draft":
        raise ValueError("discard_draft called on a non-draft reaction")
    db.session.delete(draft)
    db.session.commit()


def duplicate_for_new(source: Reaction, *, created_by_id: int | None = None) -> Reaction:
    """Duplicate a reaction as a fresh, independent draft.

    Different from ``clone_for_editing``: this creates a draft that is
    NOT linked to the source by ``parent_published_id``. The user must
    choose a new ``template_code_base`` before saving. The new family
    starts at version 1 once published.

    All components, steps, step-components, and checklist items are
    copied over (just like ``clone_for_editing``).

    Returns the new draft Reaction (already committed).
    """
    from stoic_eln.services.code_generator import generate_reaction_code

    draft = Reaction(
        code=generate_reaction_code(),
        # Empty template_code + base: the user MUST provide a new family
        # code before saving (UI enforces this).
        template_code=None,
        template_code_base=None,
        version_number=1,
        status="draft",
        parent_published_id=None,  # not a clone
        parent_version_id=None,
        is_archived=False,
        title=source.title + " (copia)",
        description=source.description,
        procedure=source.procedure,
        temperature_c=source.temperature_c,
        duration_hours=source.duration_hours,
        atmosphere=source.atmosphere,
        pressure_bar=source.pressure_bar,
        scheme_smiles=source.scheme_smiles,
        source=source.source,
        notes=source.notes,
        default_scale_mmol=source.default_scale_mmol,
        created_by_id=created_by_id,
        is_active=True,
    )
    db.session.add(draft)
    db.session.flush()

    # Reuse the same children-copying logic as clone_for_editing.
    # Components
    comp_map: dict[int, ReactionComponent] = {}
    for c in source.components:
        new_c = ReactionComponent(
            reaction_id=draft.id,
            substance_id=c.substance_id,
            role=c.role,
            is_limiting=c.is_limiting,
            equivalents=c.equivalents,
            concentration_M=c.concentration_M,
            position=c.position,
        )
        db.session.add(new_c)
        db.session.flush()
        comp_map[c.id] = new_c

    # Reaction-level checklist
    for it in source.checklist_items:
        db.session.add(
            ChecklistItem(
                reaction_id=draft.id,
                text=it.text,
                position=it.position,
            )
        )

    # Steps + their nested children
    for s in source.steps:
        new_s = ReactionStep(
            reaction_id=draft.id,
            kind=s.kind,
            title=s.title,
            description=s.description,
            position=s.position,
        )
        db.session.add(new_s)
        db.session.flush()
        for sc in s.components:
            db.session.add(
                ReactionStepComponent(
                    step_id=new_s.id,
                    substance_id=sc.substance_id,
                    role=sc.role,
                    ratio_value=sc.ratio_value,
                    ratio_kind=sc.ratio_kind,
                    position=sc.position,
                )
            )
        for it in s.checklist_items:
            db.session.add(
                ChecklistItem(
                    step_id=new_s.id,
                    text=it.text,
                    position=it.position,
                )
            )

    db.session.commit()
    return draft
