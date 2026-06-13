"""Stoic ELN — Procedure library routes.

Four concerns:

  - browse the library (index + detail panel)
  - save an existing reaction step INTO the library (create/overwrite)
  - insert a library procedure INTO a reaction (copy)
  - rename / delete library entries

Both copy directions deep-copy components and checklist items.
Library entries never reference live reaction rows and vice versa.
"""

from __future__ import annotations

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import gettext as _
from flask_login import current_user, login_required

from stoic_eln.blueprints._decorators import supervisor_required
from stoic_eln.blueprints.procedures import bp
from stoic_eln.extensions import db
from stoic_eln.models.checklist_item import ChecklistItem
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_step import STEP_KINDS, ReactionStep
from stoic_eln.models.reaction_step_component import ReactionStepComponent
from stoic_eln.models.step_template import (
    StepTemplate,
    StepTemplateChecklistItem,
    StepTemplateComponent,
)
from stoic_eln.services.audit import log_event


# ── Browse ─────────────────────────────────────────────────────────


@bp.route("/")
@login_required
def index():
    templates = StepTemplate.query.order_by(StepTemplate.name.asc()).all()
    return render_template("procedures/index.html", templates=templates)


# ── Save a reaction step into the library ──────────────────────────


@bp.route("/save-from-step/<int:step_id>", methods=["POST"])
@login_required
@supervisor_required
def save_from_step(step_id: int):
    step = db.session.get(ReactionStep, step_id)
    if step is None:
        abort(404)

    name = (request.form.get("name") or "").strip() or step.title
    overwrite = request.form.get("overwrite") == "1"

    existing = StepTemplate.query.filter(StepTemplate.name == name).first()
    if existing and not overwrite:
        flash(
            _(
                "Esiste già una procedura chiamata '%(n)s'. Spunta 'sovrascrivi' per sostituirla.",
                n=name,
            ),
            "warning",
        )
        return redirect(
            url_for("reactions.detail", reaction_id=step.reaction_id) + f"#step-card-{step.id}"
        )

    if existing:
        # Overwrite: wipe children, refresh metadata. Keeping the
        # same row id preserves nothing else of value, and the
        # cascade handles the children cleanly.
        existing.kind = step.kind
        existing.description = step.description
        existing.components.clear()
        existing.checklist_items.clear()
        tpl = existing
        action = "overwrite_procedure"
    else:
        tpl = StepTemplate(
            name=name[:200],
            kind=step.kind if step.kind in STEP_KINDS else "workup",
            description=step.description,
            created_by_id=current_user.id,
        )
        db.session.add(tpl)
        action = "create_procedure"

    for c in step.components:
        tpl.components.append(
            StepTemplateComponent(
                substance_id=c.substance_id,
                mixture_id=c.mixture_id,
                free_name=c.free_name,
                free_unit=c.free_unit,
                position=c.position,
                role=c.role,
                ratio_kind=c.ratio_kind,
                ratio_value=c.ratio_value,
                concentration_M=c.concentration_M,
                notes=c.notes,
            )
        )
    for item in step.checklist_items:
        tpl.checklist_items.append(
            StepTemplateChecklistItem(position=item.position, text=item.text)
        )

    db.session.commit()
    log_event(
        action=action,
        entity_type="step_template",
        entity_id=tpl.id,
        details={"name": tpl.name, "from_step": step.id, "reaction": step.reaction_id},
    )
    flash(_("Procedura '%(n)s' salvata nella libreria.", n=tpl.name), "success")
    return redirect(
        url_for("reactions.detail", reaction_id=step.reaction_id) + f"#step-card-{step.id}"
    )


# ── Insert a library procedure into a reaction ─────────────────────


@bp.route("/<int:template_id>/insert-into/<int:reaction_id>", methods=["POST"])
@login_required
@supervisor_required
def insert_into_reaction(template_id: int, reaction_id: int):
    tpl = db.session.get(StepTemplate, template_id)
    rxn = db.session.get(Reaction, reaction_id)
    if tpl is None or rxn is None:
        abort(404)

    next_pos = max((s.position for s in rxn.steps), default=-1) + 1
    step = ReactionStep(
        reaction_id=rxn.id,
        position=next_pos,
        kind=tpl.kind,
        title=tpl.name[:200],
        description=tpl.description,
    )
    db.session.add(step)
    db.session.flush()  # need step.id for children FKs

    for c in tpl.components:
        db.session.add(
            ReactionStepComponent(
                step_id=step.id,
                substance_id=c.substance_id,
                mixture_id=c.mixture_id,
                free_name=c.free_name,
                free_unit=c.free_unit,
                position=c.position,
                role=c.role,
                ratio_kind=c.ratio_kind,
                ratio_value=c.ratio_value,
                concentration_M=c.concentration_M,
                notes=c.notes,
            )
        )
    for item in tpl.checklist_items:
        db.session.add(ChecklistItem(step_id=step.id, position=item.position, text=item.text))

    db.session.commit()
    log_event(
        action="insert_procedure",
        entity_type="reaction",
        entity_id=rxn.id,
        details={"template": tpl.id, "template_name": tpl.name, "step_id": step.id},
    )
    flash(_("Procedura '%(n)s' inserita nel protocollo.", n=tpl.name), "success")
    return redirect(url_for("reactions.detail", reaction_id=rxn.id) + f"#step-card-{step.id}")


# ── Rename / delete ────────────────────────────────────────────────


@bp.route("/<int:template_id>/rename", methods=["POST"])
@login_required
@supervisor_required
def rename(template_id: int):
    tpl = db.session.get(StepTemplate, template_id)
    if tpl is None:
        abort(404)

    new_name = (request.form.get("name") or "").strip()
    if not new_name:
        flash(_("Il nome non può essere vuoto."), "danger")
        return redirect(url_for("procedures.index"))

    clash = StepTemplate.query.filter(
        StepTemplate.name == new_name, StepTemplate.id != tpl.id
    ).first()
    if clash:
        flash(_("Esiste già una procedura chiamata '%(n)s'.", n=new_name), "danger")
        return redirect(url_for("procedures.index"))

    old = tpl.name
    tpl.name = new_name[:200]
    db.session.commit()
    log_event(
        action="rename_procedure",
        entity_type="step_template",
        entity_id=tpl.id,
        details={"old": old, "new": tpl.name},
    )
    flash(_("Procedura rinominata."), "success")
    return redirect(url_for("procedures.index"))


@bp.route("/<int:template_id>/delete", methods=["POST"])
@login_required
@supervisor_required
def delete(template_id: int):
    tpl = db.session.get(StepTemplate, template_id)
    if tpl is None:
        abort(404)

    name = tpl.name
    db.session.delete(tpl)
    db.session.commit()
    log_event(
        action="delete_procedure",
        entity_type="step_template",
        entity_id=template_id,
        details={"name": name},
    )
    flash(_("Procedura '%(n)s' eliminata dalla libreria.", n=name), "success")
    return redirect(url_for("procedures.index"))
