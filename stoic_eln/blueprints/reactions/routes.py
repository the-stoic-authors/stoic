"""Stoic ELN — Reaction routes."""

from __future__ import annotations

import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import and_, or_

from stoic_eln.blueprints.reactions import bp
from stoic_eln.blueprints._decorators import supervisor_required
from stoic_eln.blueprints.reactions.forms import (
    ReactionComponentForm,
)
from stoic_eln.extensions import db
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_component import COMPONENT_ROLES, ReactionComponent
from stoic_eln.models.substance import Substance
from stoic_eln.services.audit import log_event
from stoic_eln.services.code_generator import generate_reaction_code

logger = logging.getLogger(__name__)


# ─── List ────────────────────────────────────────────────────────────────────


@bp.route("/")
@login_required
def list_view():
    q = request.args.get("q", "").strip()
    show_inactive = request.args.get("show_inactive") == "1"

    query = db.session.query(Reaction)

    if not show_inactive:
        query = query.filter(Reaction.is_active.is_(True))

    # Hide archived versions from the main listing — older versions of a
    # template are still in the DB but not shown unless the user clicks
    # "Versioni precedenti" on a specific template.
    query = query.filter(Reaction.is_archived.is_(False))

    # Drafts: only the author sees their own. Everyone sees published.
    query = query.filter(
        or_(
            Reaction.status == "published",
            and_(
                Reaction.status == "draft",
                Reaction.created_by_id == current_user.id,
            ),
        )
    )

    if q:
        like = f"%{q}%"
        # Search reaction fields + substance names of components
        query = (
            query.outerjoin(ReactionComponent, ReactionComponent.reaction_id == Reaction.id)
            .outerjoin(Substance, Substance.id == ReactionComponent.substance_id)
            .filter(
                or_(
                    Reaction.code.ilike(like),
                    Reaction.template_code.ilike(like),
                    Reaction.title.ilike(like),
                    Reaction.description.ilike(like),
                    Reaction.source.ilike(like),
                    Substance.name.ilike(like),
                    Substance.cas_number.ilike(like),
                )
            )
            .distinct()
        )

    query = query.order_by(Reaction.created_at.desc())
    reactions = query.all()

    if request.headers.get("HX-Request"):
        return render_template(
            "reactions/_list_table.html",
            reactions=reactions,
            q=q,
        )

    return render_template(
        "reactions/list.html",
        reactions=reactions,
        q=q,
        show_inactive=show_inactive,
    )


# ─── Detail ──────────────────────────────────────────────────────────────────


@bp.route("/<int:reaction_id>")
@login_required
def detail(reaction_id: int):
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)

    log_event(action="read", entity_type="reaction", entity_id=rxn.id)

    # Aggregate stats across all completed runs of this template family
    # (Settimana 6 patch 6).
    from stoic_eln.services.template_stats import (
        stats_for_template,
        render_sparkline_svg,
    )

    stats = None
    sparkline_svg = ""
    if rxn.template_code_base:
        stats = stats_for_template(rxn.template_code_base)
        if stats.has_data:
            sparkline_svg = render_sparkline_svg(
                stats.points,
                metric="cost_per_g",
            )

    # Notes (Settimana 6 patch 9)
    from stoic_eln.services.notes import list_notes

    notes_for_entity = list_notes("reaction", rxn.id)

    # Attachments (Settimana 6 patch 10)
    from stoic_eln.services.attachments import list_attachments

    attachments_for_entity = list_attachments("reaction", rxn.id)

    # Procedure library (for the "insert from library" picker in the
    # add-step modal). Loaded only in draft state, where steps are
    # editable — saves a query everywhere else.
    step_templates = []
    if rxn.status == "draft":
        from stoic_eln.models.step_template import StepTemplate

        step_templates = StepTemplate.query.order_by(StepTemplate.name.asc()).all()

    return render_template(
        "reactions/detail.html",
        reaction=rxn,
        scheme_smiles=rxn.derive_scheme_smiles(),
        stats=stats,
        sparkline_svg=sparkline_svg,
        notes_for_entity=notes_for_entity,
        attachments_for_entity=attachments_for_entity,
        step_templates=step_templates,
    )


# ─── Create / Edit / Save / Cancel ──────────────────────────────────────────


@bp.route("/new", methods=["POST"])
@login_required
@supervisor_required
def create():
    """Create a new draft reaction and redirect to its edit page.

    The reaction is born in status='draft' with no template_code yet —
    the user must fill in the code (and other fields) before saving.
    Drafts only show up to their author in listings.
    """
    rxn = Reaction(
        code=generate_reaction_code(),
        template_code=None,
        status="draft",
        title=_("Nuova reazione"),
        created_by_id=current_user.id,
        default_scale_mmol=1.0,
    )
    db.session.add(rxn)
    db.session.commit()
    log_event(action="create_draft", entity_type="reaction", entity_id=rxn.id)
    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


@bp.route("/<int:reaction_id>/edit", methods=["POST"])
@login_required
@supervisor_required
def edit(reaction_id: int):
    """Open a published reaction for editing by cloning it into a draft.

    If the user already has a draft of this template open, jump to it
    instead of creating a second one.
    """
    from stoic_eln.services.reaction_clone import clone_for_editing

    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)

    # If we're already on a draft, just stay on it
    if rxn.status == "draft":
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    # Look for an existing draft with the same template_code by this user
    existing_draft = (
        db.session.query(Reaction)
        .filter(
            Reaction.template_code == rxn.template_code,
            Reaction.status == "draft",
            Reaction.created_by_id == current_user.id,
        )
        .first()
    )
    if existing_draft is not None:
        flash(_("Hai già una bozza in lavorazione per questo template."), "info")
        return redirect(url_for("reactions.detail", reaction_id=existing_draft.id))

    draft = clone_for_editing(rxn, created_by_id=current_user.id)
    log_event(
        action="open_for_edit",
        entity_type="reaction",
        entity_id=draft.id,
        details={"source_id": rxn.id},
    )
    flash(
        _("Modifica in corso. Premi 'Salva' per confermare o 'Annulla' per scartare le modifiche."),
        "info",
    )
    return redirect(url_for("reactions.detail", reaction_id=draft.id))


@bp.route("/<int:reaction_id>/save", methods=["POST"])
@login_required
@supervisor_required
def save_draft(reaction_id: int):
    """Persist header fields then promote draft to published."""
    from stoic_eln.services import template_code as tc_service
    from stoic_eln.services.reaction_clone import promote_draft

    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    if rxn.status != "draft":
        flash(_("Questa reazione non è una bozza."), "warning")
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    # Persist header fields from the form
    rxn.title = _parse_required_str(request.form.get("title", ""))
    rxn.description = _parse_str(request.form.get("description", ""))
    rxn.procedure = _parse_str(request.form.get("procedure", ""))
    rxn.temperature_c = _parse_float(request.form.get("temperature_c", ""))
    rxn.duration_hours = _parse_float(request.form.get("duration_hours", ""))
    rxn.atmosphere = _parse_str(request.form.get("atmosphere", ""))
    rxn.pressure_bar = _parse_float(request.form.get("pressure_bar", ""))
    rxn.scheme_smiles = _parse_str(request.form.get("scheme_smiles", ""))
    rxn.source = _parse_str(request.form.get("source", ""))
    rxn.notes = _parse_str(request.form.get("notes", ""))
    raw_code = request.form.get("template_code", "")
    db.session.commit()

    # Validate the template_code. Special case: when the draft was created
    # via "Modifica" of an existing published reaction (parent_published_id
    # is set), the user MAY keep the same code as the parent — that's the
    # whole point of editing.
    norm = tc_service.normalize(raw_code)
    parent_id = rxn.parent_published_id

    try:
        if parent_id is not None and norm:
            # Allow the parent's existing code to coexist while we validate;
            # promote_draft will delete it. But if there's a DIFFERENT
            # published with this code, that's still a real conflict.
            extra_excludes = {rxn.id, parent_id}
            other = (
                db.session.query(Reaction)
                .filter(
                    Reaction.template_code == norm,
                    Reaction.status == "published",
                    Reaction.id.notin_(extra_excludes),
                )
                .first()
            )
            if other is not None:
                raise tc_service.TemplateCodeError(
                    f"Il codice '{norm}' è già usato da un altro template."
                )
            rxn.template_code = tc_service.validate(
                raw_code,
                exclude_id=rxn.id,
                allow_replace=True,
            )
        else:
            rxn.template_code = tc_service.validate(raw_code, exclude_id=rxn.id)
    except tc_service.TemplateCodeError as e:
        flash(str(e), "danger")
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    # Validate title
    if not rxn.title or rxn.title.strip() in ("", _("Nuova reazione")):
        flash(_("Inserisci un titolo per la reazione prima di salvare."), "danger")
        db.session.commit()
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    try:
        promote_draft(rxn)
    except tc_service.TemplateCodeError as e:
        flash(str(e), "danger")
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))
    log_event(action="publish", entity_type="reaction", entity_id=rxn.id)
    flash(_("Template '%(code)s' salvato.", code=rxn.template_code), "success")
    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


@bp.route("/<int:reaction_id>/cancel", methods=["POST"])
@login_required
@supervisor_required
def cancel_draft(reaction_id: int):
    """Discard a draft. If there's a published version with the same
    template_code, redirect there; otherwise back to the list."""
    from stoic_eln.services.reaction_clone import discard_draft

    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    if rxn.status != "draft":
        flash(_("Questa reazione non è una bozza."), "warning")
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    # Look for sibling published version
    sibling = None
    if rxn.template_code:
        sibling = (
            db.session.query(Reaction)
            .filter(
                Reaction.template_code == rxn.template_code,
                Reaction.status == "published",
                Reaction.id != rxn.id,
            )
            .first()
        )

    discard_draft(rxn)
    log_event(action="discard_draft", entity_type="reaction", entity_id=reaction_id)
    flash(_("Modifiche scartate."), "info")
    if sibling is not None:
        return redirect(url_for("reactions.detail", reaction_id=sibling.id))
    return redirect(url_for("reactions.list_view"))


# ─── Inline field update (HTMX) ──────────────────────────────────────────────


# Fields that can be updated inline on the detail page.
# Maps form field name → (column attribute, parser callable returning new value or None).
def _parse_str(v: str) -> str | None:
    v = (v or "").strip()
    return v or None


def _parse_required_str(v: str) -> str:
    """Title can never be fully empty — fall back to placeholder."""
    v = (v or "").strip()
    return v if v else "Nuova reazione"


def _parse_float(v: str) -> float | None:
    v = (v or "").strip().replace(",", ".")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _parse_template_code(v: str) -> str | None:
    """Normalize but don't fully validate (uniqueness check happens at save).

    The user might type the code progressively; we don't want to block them
    while they're still typing. Final validation happens in ``save_draft``.

    Note: this returns the BASE code (no version suffix). The actual
    versioned ``template_code`` is computed by ``promote_draft``.
    """
    from stoic_eln.services import template_code as tc

    norm = tc.normalize(v)
    # Strip a trailing '.N' in case the user pasted a versioned code
    split = tc.split_versioned(norm)
    if split:
        norm = split[0]
    return norm or None


_INLINE_FIELDS: dict[str, tuple[str, callable]] = {
    "title": ("title", _parse_required_str),
    "description": ("description", _parse_str),
    "procedure": ("procedure", _parse_str),
    "temperature_c": ("temperature_c", _parse_float),
    "duration_hours": ("duration_hours", _parse_float),
    "atmosphere": ("atmosphere", _parse_str),
    "pressure_bar": ("pressure_bar", _parse_float),
    "scheme_smiles": ("scheme_smiles", _parse_str),
    "source": ("source", _parse_str),
    "notes": ("notes", _parse_str),
    # Note: when the user types in the "template_code" input, we save
    # to ``template_code_base`` (the family code). The actual versioned
    # ``template_code`` is generated at publish time by promote_draft.
    "template_code": ("template_code_base", _parse_template_code),
}


@bp.route("/<int:reaction_id>/header", methods=["POST"])
@login_required
@supervisor_required
def update_header(reaction_id: int):
    """Bulk-update the reaction header fields from the main form.

    Called via formaction by the "Salva" button (which posts to
    save_draft instead). This route is here as a fallback for users
    with JS disabled — it just persists the fields without promoting
    the draft.
    """
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)

    rxn.template_code_base = _parse_template_code(request.form.get("template_code", ""))
    rxn.title = _parse_required_str(request.form.get("title", ""))
    rxn.description = _parse_str(request.form.get("description", ""))
    rxn.procedure = _parse_str(request.form.get("procedure", ""))
    rxn.temperature_c = _parse_float(request.form.get("temperature_c", ""))
    rxn.duration_hours = _parse_float(request.form.get("duration_hours", ""))
    rxn.atmosphere = _parse_str(request.form.get("atmosphere", ""))
    rxn.pressure_bar = _parse_float(request.form.get("pressure_bar", ""))
    rxn.scheme_smiles = _parse_str(request.form.get("scheme_smiles", ""))
    rxn.source = _parse_str(request.form.get("source", ""))
    rxn.notes = _parse_str(request.form.get("notes", ""))

    db.session.commit()
    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


@bp.route("/<int:reaction_id>/field", methods=["POST"])
@login_required
@supervisor_required
def update_field(reaction_id: int):
    """HTMX inline-edit endpoint for any of the reaction-level scalar fields."""
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)

    field = request.form.get("field")
    if field not in _INLINE_FIELDS:
        abort(400)

    column, parser = _INLINE_FIELDS[field]
    # Two calling conventions:
    #   1. Legacy: form has a generic "value" key (used by some inline edits)
    #   2. HTMX auto-save: the input keeps its semantic name (e.g. "title");
    #      we look it up under that name.
    if "value" in request.form:
        raw = request.form.get("value", "")
    else:
        raw = request.form.get(field, "")
    setattr(rxn, column, parser(raw))
    db.session.commit()

    if request.headers.get("HX-Request"):
        # Empty 204 — the input keeps its current value, no DOM swap needed.
        return "", 204
    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


# Legacy route, kept for backwards compatibility (used by initial template).
@bp.route("/<int:reaction_id>/procedure", methods=["POST"])
@login_required
@supervisor_required
def update_procedure(reaction_id: int):
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    rxn.procedure = (request.form.get("procedure") or "").strip() or None
    db.session.commit()
    if request.headers.get("HX-Request"):
        return "", 204
    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


# ─── (De)activate ────────────────────────────────────────────────────────────


@bp.route("/<int:reaction_id>/deactivate", methods=["POST"])
@login_required
@supervisor_required
def deactivate(reaction_id: int):
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    rxn.is_active = False
    db.session.commit()
    log_event(action="deactivate", entity_type="reaction", entity_id=rxn.id)
    flash(_("Reazione %(code)s disattivata.", code=rxn.code), "info")
    return redirect(url_for("reactions.list_view"))


@bp.route("/<int:reaction_id>/reactivate", methods=["POST"])
@login_required
@supervisor_required
def reactivate(reaction_id: int):
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    rxn.is_active = True
    db.session.commit()
    log_event(action="reactivate", entity_type="reaction", entity_id=rxn.id)
    flash(_("Reazione %(code)s riattivata.", code=rxn.code), "info")
    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


# ─── Component management ───────────────────────────────────────────────────
# These are the routes used by the inline editor in detail.html. Each operates
# on a single component and returns either a redirect (full request) or the
# refreshed component table partial (HTMX request).


@bp.route("/<int:reaction_id>/components/new", methods=["POST"])
@login_required
@supervisor_required
def add_component(reaction_id: int):
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)

    form = ReactionComponentForm()
    if not form.validate_on_submit():
        flash(_("Dati componente non validi."), "danger")
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    if form.role.data not in COMPONENT_ROLES:
        flash(_("Ruolo non valido."), "danger")
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    # XOR resolution: the form may provide substance_id, mixture_id,
    # or neither (invalid). The UI ensures exactly one picker fires,
    # so receiving both is a tampering attempt — we reject.
    sub_id = form.substance_id.data
    mix_id = form.mixture_id.data
    if (sub_id and mix_id) or (not sub_id and not mix_id):
        flash(
            _("Seleziona esattamente una tra Sostanza e Miscela."),
            "danger",
        )
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    sub = None
    mix = None
    if sub_id:
        sub = db.session.get(Substance, sub_id)
        if sub is None:
            flash(_("Sostanza non trovata."), "danger")
            return redirect(url_for("reactions.detail", reaction_id=rxn.id))
    else:
        from stoic_eln.models.mixture import Mixture

        mix = db.session.get(Mixture, mix_id)
        if mix is None:
            flash(_("Miscela non trovata."), "danger")
            return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    # Roles that aren't configured in the template
    is_product = form.role.data in ("product", "byproduct")
    is_solvent = form.role.data == "solvent"

    # Determine equivalents:
    # - products/byproducts: no equivalents (they're outputs, not inputs)
    # - solvents: no equivalents (use concentration instead)
    # - non-limiting components: use whatever the user typed, default None
    # - limiting (= starting_material as the first one): always 1.0
    equivalents: float | None
    if is_product or is_solvent:
        equivalents = None
    else:
        equivalents = form.equivalents.data

    # Concentration is only meaningful for solvents
    concentration_M = form.concentration_M.data if is_solvent else None

    # Limiting flag: only the first SM-style component becomes limiting,
    # and only one limiting per reaction.
    if form.is_limiting.data:
        for existing in rxn.components:
            existing.is_limiting = False

    is_limiting = bool(form.is_limiting.data)
    if (
        not is_limiting
        and not any(c.is_limiting for c in rxn.components)
        and form.role.data in ("starting_material", "reactant")
    ):
        is_limiting = True

    if is_limiting:
        equivalents = 1.0

    next_position = max((c.position for c in rxn.components), default=-1) + 1

    component = ReactionComponent(
        reaction_id=rxn.id,
        substance_id=sub.id if sub else None,
        mixture_id=mix.id if mix else None,
        role=form.role.data,
        position=next_position,
        equivalents=equivalents,
        amount_mmol=None,  # not stored in template
        amount_g=None,
        amount_mL=None,
        is_limiting=is_limiting,
        concentration_M=concentration_M,
        notes=form.notes.data or None,
    )
    db.session.add(component)
    db.session.commit()
    log_event(
        action="add_component",
        entity_type="reaction",
        entity_id=rxn.id,
        details={
            "component_id": component.id,
            "substance_id": sub.id if sub else None,
            "mixture_id": mix.id if mix else None,
            "role": form.role.data,
        },
    )

    if request.headers.get("HX-Request"):
        return render_template("reactions/_components_table.html", reaction=rxn, is_draft=True)

    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


@bp.route("/components/<int:component_id>/delete", methods=["POST"])
@login_required
@supervisor_required
def delete_component(component_id: int):
    component = db.session.get(ReactionComponent, component_id)
    if component is None:
        abort(404)
    rxn = component.reaction
    db.session.delete(component)
    db.session.commit()
    log_event(
        action="delete_component",
        entity_type="reaction",
        entity_id=rxn.id,
        details={"component_id": component_id},
    )

    if request.headers.get("HX-Request"):
        return render_template("reactions/_components_table.html", reaction=rxn, is_draft=True)

    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


@bp.route("/components/<int:component_id>/edit", methods=["POST"])
@login_required
@supervisor_required
def edit_component(component_id: int):
    """Inline-edit a single field on a component. HTMX-driven.

    Template-level fields only: equivalents (for non-solvent inputs),
    concentration_M (for solvents), is_limiting (toggle).
    Absolute quantities (g/mL/mmol) belong to a Run, not the template.
    """
    component = db.session.get(ReactionComponent, component_id)
    if component is None:
        abort(404)
    rxn = component.reaction

    field = request.form.get("field")
    raw_value = request.form.get("value", "").strip()

    if field not in ("equivalents", "concentration_M", "is_limiting"):
        abort(400)

    if field == "is_limiting":
        new_val = raw_value in ("1", "true", "on", "yes")
        if new_val:
            for c in rxn.components:
                c.is_limiting = c.id == component.id
            # The new limiting reagent always gets eq=1 by convention
            component.equivalents = 1.0
        else:
            component.is_limiting = False
    else:
        try:
            num = float(raw_value.replace(",", ".")) if raw_value else None
        except ValueError:
            num = None

        # Don't allow editing equivalents on the limiting reagent (always 1.0)
        # and ignore equivalents on products/byproducts/solvents.
        if field == "equivalents":
            if component.is_limiting:
                component.equivalents = 1.0
            elif component.role in ("product", "byproduct", "solvent"):
                component.equivalents = None
            else:
                component.equivalents = num
        elif field == "concentration_M":
            # Only meaningful for solvents
            if component.role == "solvent":
                component.concentration_M = num
            else:
                component.concentration_M = None

    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template("reactions/_components_table.html", reaction=rxn, is_draft=True)

    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _limiting_mmol_for(rxn: Reaction, exclude: int | None = None) -> float | None:
    """Return mmol of the limiting reagent in this reaction, if any."""
    for c in rxn.components:
        if exclude is not None and c.id == exclude:
            continue
        if c.is_limiting and c.amount_mmol:
            return c.amount_mmol
    return None


# ─── Reaction-level scale ────────────────────────────────────────────────────


@bp.route("/<int:reaction_id>/scale", methods=["POST"])
@login_required
@supervisor_required
def update_scale(reaction_id: int):
    """Update the default_scale_mmol used to preview absolute quantities."""
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    raw = request.form.get("scale", "1.0").strip().replace(",", ".")
    try:
        scale = float(raw)
        if scale <= 0:
            scale = 1.0
    except ValueError:
        scale = 1.0
    rxn.default_scale_mmol = scale
    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template("reactions/_components_table.html", reaction=rxn, is_draft=True)
    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


# ─── Checklist (reaction-level) ──────────────────────────────────────────────


@bp.route("/<int:reaction_id>/checklist/new", methods=["POST"])
@login_required
@supervisor_required
def add_checklist_item(reaction_id: int):
    from stoic_eln.models.checklist_item import ChecklistItem

    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)

    text = (request.form.get("text") or "").strip()
    if not text:
        if request.headers.get("HX-Request"):
            return render_template(
                "reactions/_checklist.html",
                items=rxn.checklist_items,
                parent_kind="reaction",
                parent_id=rxn.id,
                can_edit=True,
            )
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    next_pos = max((c.position for c in rxn.checklist_items), default=-1) + 1
    item = ChecklistItem(reaction_id=rxn.id, position=next_pos, text=text[:500])
    db.session.add(item)
    db.session.commit()
    log_event(
        action="add_checklist",
        entity_type="reaction",
        entity_id=rxn.id,
        details={"text": item.text},
    )

    if request.headers.get("HX-Request"):
        # Refresh the entire reaction-level checklist
        db.session.refresh(rxn)
        return render_template(
            "reactions/_checklist.html",
            items=rxn.checklist_items,
            parent_kind="reaction",
            parent_id=rxn.id,
            can_edit=True,
        )
    return redirect(url_for("reactions.detail", reaction_id=rxn.id))


@bp.route("/<int:step_id>/checklist/step/new", methods=["POST"])
@login_required
@supervisor_required
def add_step_checklist_item(step_id: int):
    """Add a checklist item to a specific step."""
    from stoic_eln.models.checklist_item import ChecklistItem
    from stoic_eln.models.reaction_step import ReactionStep

    step = db.session.get(ReactionStep, step_id)
    if step is None:
        abort(404)

    text = (request.form.get("text") or "").strip()
    if text:
        next_pos = max((c.position for c in step.checklist_items), default=-1) + 1
        item = ChecklistItem(step_id=step.id, position=next_pos, text=text[:500])
        db.session.add(item)
        db.session.commit()
        log_event(
            action="add_checklist",
            entity_type="reaction_step",
            entity_id=step.id,
            details={"text": item.text},
        )

    if request.headers.get("HX-Request"):
        db.session.refresh(step)
        return render_template(
            "reactions/_checklist.html",
            items=step.checklist_items,
            parent_kind="step",
            parent_id=step.id,
            can_edit=True,
        )
    return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))


@bp.route("/checklist/<int:item_id>/toggle", methods=["POST"])
@login_required
@supervisor_required
def toggle_checklist_item(item_id: int):
    from stoic_eln.models.checklist_item import ChecklistItem

    item = db.session.get(ChecklistItem, item_id)
    if item is None:
        abort(404)

    item.is_default_done = not item.is_default_done
    db.session.commit()

    if request.headers.get("HX-Request"):
        # Render just this row swap
        return render_template("reactions/_checklist_row.html", item=item)
    if item.reaction_id:
        return redirect(url_for("reactions.detail", reaction_id=item.reaction_id))
    step = item.step
    return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))


@bp.route("/checklist/<int:item_id>/row", methods=["GET"])
@login_required
def checklist_row(item_id: int):
    """Render a single checklist row.

    Query string:
      - edit=1 → render in edit mode (text becomes editable input)

    Used by HTMX to swap a row in/out of edit mode without a full page reload.
    """
    from stoic_eln.models.checklist_item import ChecklistItem

    item = db.session.get(ChecklistItem, item_id)
    if item is None:
        abort(404)
    edit_mode = request.args.get("edit") == "1"
    return render_template(
        "reactions/_checklist_row.html",
        item=item,
        edit_mode=edit_mode,
    )


@bp.route("/checklist/<int:item_id>/edit", methods=["POST"])
@login_required
@supervisor_required
def edit_checklist_item(item_id: int):
    """Update the text of an existing checklist item."""
    from stoic_eln.models.checklist_item import ChecklistItem

    item = db.session.get(ChecklistItem, item_id)
    if item is None:
        abort(404)

    new_text = (request.form.get("text") or "").strip()
    if not new_text:
        # Empty text -> treat as a no-op, just re-render the row.
        if request.headers.get("HX-Request"):
            return render_template("reactions/_checklist_row.html", item=item)
        return redirect(
            url_for(
                "reactions.detail",
                reaction_id=item.reaction_id or item.step.reaction_id,
            )
        )

    item.text = new_text
    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template("reactions/_checklist_row.html", item=item)
    return redirect(
        url_for(
            "reactions.detail",
            reaction_id=item.reaction_id or item.step.reaction_id,
        )
    )


@bp.route("/checklist/<int:item_id>/delete", methods=["POST"])
@login_required
@supervisor_required
def delete_checklist_item(item_id: int):
    from stoic_eln.models.checklist_item import ChecklistItem

    item = db.session.get(ChecklistItem, item_id)
    if item is None:
        abort(404)

    parent_kind = "reaction" if item.reaction_id else "step"
    parent_id = item.reaction_id or item.step_id
    rid_for_redirect = item.reaction_id or item.step.reaction_id

    db.session.delete(item)
    db.session.commit()

    if request.headers.get("HX-Request"):
        # Re-fetch sibling items
        if parent_kind == "reaction":
            rxn = db.session.get(Reaction, parent_id)
            items = rxn.checklist_items if rxn else []
        else:
            from stoic_eln.models.reaction_step import ReactionStep

            step = db.session.get(ReactionStep, parent_id)
            items = step.checklist_items if step else []
        return render_template(
            "reactions/_checklist.html",
            items=items,
            parent_kind=parent_kind,
            parent_id=parent_id,
            can_edit=True,
        )
    return redirect(url_for("reactions.detail", reaction_id=rid_for_redirect))


@bp.route("/checklist/<int:item_id>/move/<direction>", methods=["POST"])
@login_required
@supervisor_required
def move_checklist_item(item_id: int, direction: str):
    """Move a checklist item up or down within its parent."""
    from stoic_eln.models.checklist_item import ChecklistItem

    if direction not in ("up", "down"):
        abort(400)

    item = db.session.get(ChecklistItem, item_id)
    if item is None:
        abort(404)

    # Get siblings sorted by position
    if item.reaction_id:
        siblings = (
            db.session.query(ChecklistItem)
            .filter(
                ChecklistItem.reaction_id == item.reaction_id,
                ChecklistItem.step_id.is_(None),
            )
            .order_by(ChecklistItem.position.asc())
            .all()
        )
        rid_for_redirect = item.reaction_id
        parent_kind, parent_id = "reaction", item.reaction_id
    else:
        siblings = (
            db.session.query(ChecklistItem)
            .filter(ChecklistItem.step_id == item.step_id)
            .order_by(ChecklistItem.position.asc())
            .all()
        )
        rid_for_redirect = item.step.reaction_id
        parent_kind, parent_id = "step", item.step_id

    idx = next((i for i, s in enumerate(siblings) if s.id == item.id), None)
    if idx is None:
        abort(500)

    if direction == "up" and idx > 0:
        siblings[idx - 1], siblings[idx] = siblings[idx], siblings[idx - 1]
    elif direction == "down" and idx < len(siblings) - 1:
        siblings[idx + 1], siblings[idx] = siblings[idx], siblings[idx + 1]

    # Re-number positions
    for i, s in enumerate(siblings):
        s.position = i
    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template(
            "reactions/_checklist.html",
            items=siblings,
            parent_kind=parent_kind,
            parent_id=parent_id,
            can_edit=True,
        )
    return redirect(url_for("reactions.detail", reaction_id=rid_for_redirect))


# ─── Steps (workup / extraction / purification / etc.) ──────────────────────


@bp.route("/<int:reaction_id>/steps/new", methods=["POST"])
@login_required
@supervisor_required
def add_step(reaction_id: int):
    from stoic_eln.models.reaction_step import STEP_KINDS, ReactionStep

    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)

    title = (request.form.get("title") or "").strip()
    kind = (request.form.get("kind") or "workup").strip()
    description = (request.form.get("description") or "").strip() or None

    if not title:
        flash(_("Il titolo dello step è obbligatorio."), "danger")
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    if kind not in STEP_KINDS:
        kind = "workup"

    next_pos = max((s.position for s in rxn.steps), default=-1) + 1
    step = ReactionStep(
        reaction_id=rxn.id,
        position=next_pos,
        kind=kind,
        title=title[:200],
        description=description,
    )
    db.session.add(step)
    db.session.commit()
    log_event(
        action="add_step",
        entity_type="reaction",
        entity_id=rxn.id,
        details={"step_id": step.id, "kind": step.kind, "title": step.title},
    )
    flash(_("Step '%(t)s' aggiunto.", t=step.title), "success")
    # Anchor to the newly-added step so the page doesn't jump back
    # to the top after the redirect — keeps the user in context.
    return redirect(url_for("reactions.detail", reaction_id=rxn.id) + f"#step-card-{step.id}")


@bp.route("/steps/<int:step_id>/edit", methods=["POST"])
@login_required
@supervisor_required
def edit_step(step_id: int):
    from stoic_eln.models.reaction_step import STEP_KINDS, ReactionStep

    step = db.session.get(ReactionStep, step_id)
    if step is None:
        abort(404)

    field = request.form.get("field")
    value = request.form.get("value", "").strip()

    if field == "title":
        if value:
            step.title = value[:200]
    elif field == "description":
        step.description = value or None
    elif field == "kind":
        if value in STEP_KINDS:
            step.kind = value
    elif field == "reference_component_id":
        # Empty string → use limiting; otherwise try to set the FK
        if value == "" or value == "limiting":
            step.reference_component_id = None
        else:
            try:
                cid = int(value)
                # Validate it belongs to the same reaction
                from stoic_eln.models.reaction_component import ReactionComponent

                rc = db.session.get(ReactionComponent, cid)
                if rc and rc.reaction_id == step.reaction_id:
                    step.reference_component_id = cid
            except (TypeError, ValueError):
                pass
    else:
        abort(400)

    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template(
            "reactions/_step_card.html", step=step, reaction=step.reaction, is_draft=True
        )
    return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))


@bp.route("/steps/<int:step_id>/delete", methods=["POST"])
@login_required
@supervisor_required
def delete_step(step_id: int):
    from stoic_eln.models.reaction_step import ReactionStep

    step = db.session.get(ReactionStep, step_id)
    if step is None:
        abort(404)
    rid = step.reaction_id
    db.session.delete(step)
    db.session.commit()
    flash(_("Step rimosso."), "info")
    return redirect(url_for("reactions.detail", reaction_id=rid))


@bp.route("/steps/<int:step_id>/move/<direction>", methods=["POST"])
@login_required
@supervisor_required
def move_step(step_id: int, direction: str):
    from stoic_eln.models.reaction_step import ReactionStep

    if direction not in ("up", "down"):
        abort(400)
    step = db.session.get(ReactionStep, step_id)
    if step is None:
        abort(404)

    siblings = (
        db.session.query(ReactionStep)
        .filter_by(reaction_id=step.reaction_id)
        .order_by(ReactionStep.position.asc())
        .all()
    )
    idx = next(i for i, s in enumerate(siblings) if s.id == step.id)
    if direction == "up" and idx > 0:
        siblings[idx - 1], siblings[idx] = siblings[idx], siblings[idx - 1]
    elif direction == "down" and idx < len(siblings) - 1:
        siblings[idx + 1], siblings[idx] = siblings[idx], siblings[idx + 1]
    for i, s in enumerate(siblings):
        s.position = i
    db.session.commit()
    return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))


# ─── Step components ────────────────────────────────────────────────────────


@bp.route("/steps/<int:step_id>/components/new", methods=["POST"])
@login_required
@supervisor_required
def add_step_component(step_id: int):
    from stoic_eln.models.reaction_step import ReactionStep
    from stoic_eln.models.reaction_step_component import (
        RATIO_KINDS,
        ReactionStepComponent,
    )

    step = db.session.get(ReactionStep, step_id)
    if step is None:
        abort(404)

    # XOR a 3 vie: substance, mixture, OR free entry (P2). Mirrors
    # reactions.add_component (patch 13.5) plus the non-inventory
    # line case ("Column Ø", "Celite pad", ...).
    try:
        substance_id = int(request.form.get("substance_id", "0"))
    except (TypeError, ValueError):
        substance_id = 0
    try:
        mixture_id = int(request.form.get("mixture_id", "0"))
    except (TypeError, ValueError):
        mixture_id = 0
    free_name = (request.form.get("free_name") or "").strip()
    free_unit = (request.form.get("free_unit") or "").strip() or None

    picked = sum(1 for x in (substance_id, mixture_id, free_name) if x)
    if picked != 1:
        flash(
            _("Seleziona esattamente una tra Sostanza, Miscela e Voce libera."),
            "danger",
        )
        return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))

    sub = None
    mix = None
    if substance_id:
        sub = db.session.get(Substance, substance_id)
        if sub is None:
            flash(_("Sostanza non trovata."), "danger")
            return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))
    elif mixture_id:
        from stoic_eln.models.mixture import Mixture

        mix = db.session.get(Mixture, mixture_id)
        if mix is None:
            flash(_("Miscela non trovata."), "danger")
            return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))
    # else: free entry (P2) — no inventory lookup needed.

    role = (request.form.get("role") or "solvent").strip()
    if role not in COMPONENT_ROLES:
        role = "solvent"

    ratio_kind = (request.form.get("ratio_kind") or "eq").strip()
    if ratio_kind not in RATIO_KINDS:
        ratio_kind = "eq"

    raw_value = (request.form.get("ratio_value") or "").strip().replace(",", ".")
    try:
        ratio_value = float(raw_value) if raw_value else None
    except ValueError:
        ratio_value = None
    # "free" kind means no target value at template time — operator
    # records the actual volume at run time (chromatography eluent
    # use case).
    if ratio_kind == "free":
        ratio_value = None

    raw_conc = (request.form.get("concentration_M") or "").strip().replace(",", ".")
    try:
        conc = float(raw_conc) if raw_conc else None
    except ValueError:
        conc = None

    next_pos = max((c.position for c in step.components), default=-1) + 1

    sc = ReactionStepComponent(
        step_id=step.id,
        substance_id=sub.id if sub else None,
        mixture_id=mix.id if mix else None,
        free_name=free_name[:120] if free_name else None,
        free_unit=free_unit[:20] if free_unit else None,
        position=next_pos,
        role=role,
        ratio_kind=ratio_kind,
        ratio_value=ratio_value,
        concentration_M=conc,
        notes=(request.form.get("notes") or "").strip() or None,
    )
    db.session.add(sc)
    db.session.commit()
    log_event(
        action="add_step_component",
        entity_type="reaction_step",
        entity_id=step.id,
        details={
            "step_component_id": sc.id,
            "substance_id": sub.id if sub else None,
            "mixture_id": mix.id if mix else None,
        },
    )

    if request.headers.get("HX-Request"):
        return render_template(
            "reactions/_step_card.html",
            step=step,
            reaction=step.reaction,
            is_draft=True,
        )
    return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))


@bp.route("/step-components/<int:scid>/edit", methods=["POST"])
@login_required
@supervisor_required
def edit_step_component(scid: int):
    from stoic_eln.models.reaction_step_component import (
        RATIO_KINDS,
        ReactionStepComponent,
    )

    sc = db.session.get(ReactionStepComponent, scid)
    if sc is None:
        abort(404)

    field = request.form.get("field")
    value = (request.form.get("value") or "").strip()

    if field == "ratio_value":
        try:
            sc.ratio_value = float(value.replace(",", ".")) if value else None
        except ValueError:
            pass
    elif field == "ratio_kind":
        if value in RATIO_KINDS:
            sc.ratio_kind = value
            # Switching to 'free' (no template target) clears the
            # ratio_value: the operator will record the actual at run.
            if value == "free":
                sc.ratio_value = None
    elif field == "role":
        if value in COMPONENT_ROLES:
            sc.role = value
    elif field == "concentration_M":
        try:
            sc.concentration_M = float(value.replace(",", ".")) if value else None
        except ValueError:
            pass
    elif field == "notes":
        sc.notes = value or None
    else:
        abort(400)

    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template(
            "reactions/_step_card.html", step=sc.step, reaction=sc.step.reaction, is_draft=True
        )
    return redirect(url_for("reactions.detail", reaction_id=sc.step.reaction_id))


@bp.route("/step-components/<int:scid>/delete", methods=["POST"])
@login_required
@supervisor_required
def delete_step_component(scid: int):
    from stoic_eln.models.reaction_step_component import ReactionStepComponent

    sc = db.session.get(ReactionStepComponent, scid)
    if sc is None:
        abort(404)
    rid = sc.step.reaction_id
    db.session.delete(sc)
    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template(
            "reactions/_step_card.html", step=sc.step, reaction=sc.step.reaction, is_draft=True
        )
    return redirect(url_for("reactions.detail", reaction_id=rid))


# ─── Step parameters (P3 — manual add/delete) ───────────────────────────────


@bp.route("/step/<int:step_id>/parameters/add", methods=["POST"])
@login_required
@supervisor_required
def add_step_parameter(step_id: int):
    """Add a StepParameter (label + unit) to a reaction step."""
    from stoic_eln.models.reaction_step import ReactionStep
    from stoic_eln.models.step_parameter import StepParameter

    step = db.session.get(ReactionStep, step_id)
    if step is None:
        abort(404)

    label = (request.form.get("label") or "").strip()[:120]
    unit = (request.form.get("unit") or "").strip()[:20] or None

    if label:
        next_pos = max((p.position for p in step.parameters), default=-1) + 1
        param = StepParameter(step_id=step.id, position=next_pos, label=label, unit=unit)
        db.session.add(param)
        db.session.commit()
        log_event(
            action="add_step_parameter",
            entity_type="reaction_step",
            entity_id=step.id,
            details={"label": label, "unit": unit},
        )

    if request.headers.get("HX-Request"):
        db.session.refresh(step)
        return render_template(
            "reactions/_step_card.html",
            step=step,
            reaction=step.reaction,
            is_draft=True,
        )
    return redirect(url_for("reactions.detail", reaction_id=step.reaction_id))


@bp.route("/step/parameters/<int:param_id>/delete", methods=["POST"])
@login_required
@supervisor_required
def delete_step_parameter(param_id: int):
    """Delete a StepParameter from a reaction step."""
    from stoic_eln.models.step_parameter import StepParameter

    param = db.session.get(StepParameter, param_id)
    if param is None:
        abort(404)

    step = param.step
    rid = step.reaction_id
    db.session.delete(param)
    db.session.commit()

    if request.headers.get("HX-Request"):
        db.session.refresh(step)
        return render_template(
            "reactions/_step_card.html",
            step=step,
            reaction=step.reaction,
            is_draft=True,
        )
    return redirect(url_for("reactions.detail", reaction_id=rid))


# ─── Run execution placeholder (Settimana 4) ────────────────────────────────


@bp.route("/<int:reaction_id>/run", methods=["GET"])
@login_required
def run_placeholder(reaction_id: int):
    """Placeholder for the actual run execution flow.

    Settimana 4 will implement: scaling, batch picking from inventory,
    inventory deduction, run record creation, yield calculation.
    For now this just shows a 'coming soon' page so the button on the
    list and detail pages does something reasonable.
    """
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    return render_template("reactions/run_placeholder.html", reaction=rxn)


# ─── Versioning (Settimana 4 patch 9) ────────────────────────────────────


@bp.route("/<int:reaction_id>/duplicate", methods=["POST"])
@login_required
@supervisor_required
def duplicate(reaction_id: int):
    """Create a fresh draft as a copy of an existing reaction (no versioning link)."""
    from stoic_eln.services.reaction_clone import duplicate_for_new

    src = db.session.get(Reaction, reaction_id)
    if src is None:
        abort(404)

    draft = duplicate_for_new(src, created_by_id=current_user.id)
    log_event(
        action="duplicate_reaction",
        entity_type="reaction",
        entity_id=draft.id,
        details={"source_id": src.id},
    )
    flash(_("Reazione duplicata. Inserisci un nuovo codice prima di salvare."), "info")
    return redirect(url_for("reactions.detail", reaction_id=draft.id))


@bp.route("/<int:reaction_id>/versions", methods=["GET"])
@login_required
def versions(reaction_id: int):
    """Show all versions (current + archived) of a template family."""
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)

    base = rxn.template_code_base
    if not base:
        # Legacy: no base set; show only this row.
        return render_template("reactions/versions.html", current=rxn, versions=[rxn])

    versions_list = (
        db.session.query(Reaction)
        .filter(Reaction.template_code_base == base)
        .order_by(Reaction.version_number.desc())
        .all()
    )
    current = next(
        (v for v in versions_list if v.status == "published" and not v.is_archived),
        versions_list[0] if versions_list else None,
    )
    return render_template("reactions/versions.html", current=current, versions=versions_list)


# ─── Settimana 6 patch 6 — Pagina statistiche template ─────────────


@bp.route("/<int:reaction_id>/stats")
@login_required
def stats(reaction_id: int):
    """Detailed stats page for the template family of this reaction.

    Shows:
      - aggregate numbers (avg/min/max cost €, €/g, yield)
      - sparkline of €/g over time
      - sparkline of yield % over time
      - table of all completed runs with their per-run metrics
    """
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    if not rxn.template_code_base:
        flash(_("Questa reazione non ha un codice template."), "warning")
        return redirect(url_for("reactions.detail", reaction_id=rxn.id))

    from stoic_eln.services.template_stats import (
        stats_for_template,
        render_sparkline_svg,
    )

    stats_data = stats_for_template(rxn.template_code_base)

    sparkline_cost_per_g = render_sparkline_svg(
        stats_data.points,
        metric="cost_per_g",
        width=600,
        height=140,
    )
    sparkline_cost_per_mol = render_sparkline_svg(
        stats_data.points,
        metric="cost_per_mol",
        width=600,
        height=140,
        color="#6f42c1",
    )
    sparkline_yield = render_sparkline_svg(
        stats_data.points,
        metric="yield_percent",
        width=600,
        height=140,
        color="#198754",
    )
    sparkline_cost_eur = render_sparkline_svg(
        stats_data.points,
        metric="cost_eur",
        width=600,
        height=140,
        color="#dc3545",
    )

    return render_template(
        "reactions/stats.html",
        reaction=rxn,
        stats=stats_data,
        sparkline_cost_per_g=sparkline_cost_per_g,
        sparkline_cost_per_mol=sparkline_cost_per_mol,
        sparkline_yield=sparkline_yield,
        sparkline_cost_eur=sparkline_cost_eur,
    )
