"""Stoic ELN — Mixture routes.

CRUD per ``Mixture`` and inline management of its ``MixtureComponent``
rows. Components are parsed out of ``request.form`` arrays in
``_parse_component_rows``; the form (``MixtureForm``) only handles
top-level fields.
"""

from __future__ import annotations

import logging

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
from sqlalchemy import func, or_

from stoic_eln.blueprints._decorators import supervisor_required
from stoic_eln.blueprints.mixtures import bp
from stoic_eln.blueprints.mixtures.forms import MixtureForm
from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.mixture import (
    COMPONENT_ROLES,
    Mixture,
    MixtureComponent,
)
from stoic_eln.models.substance import Substance
from stoic_eln.services.audit import log_event
from stoic_eln.services.hazard_phrases import (
    resolve_phrases as _phrase_dict,
)
from stoic_eln.services.prep_service import (
    ConsumptionInput,
    PrepInput,
    execute_preparation,
    suggest_consumptions,
)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────


def _parse_phrase_codes(text: str) -> list[str]:
    """Split 'H225, H319, H336' into ['H225', 'H319', 'H336']."""
    if not text:
        return []
    return [c.strip().upper() for c in text.split(",") if c.strip()]


def _parse_component_rows(form_data) -> list[dict]:
    """Extract component rows from the multi-row form.

    The component-rows portion of the form uses parallel arrays:
    ``component_kind[]`` (values: "substance" or "mixture"),
    ``component_ref_id[]`` (substance.id when kind=substance,
    mixture.id when kind=mixture),
    ``component_role[]``,
    ``component_concentration[]``, ``component_concentration_unit[]``,
    ``component_notes[]``. This function zips them together and
    discards rows where the ref isn't selected (the user added
    an empty row but didn't fill it in — common after clicking
    "Add row" and then changing one's mind).

    Backward-compat: also reads the legacy ``component_substance_id[]``
    array when ``component_kind[]`` isn't present, so old form
    submissions or programmatic callers don't break.

    Returns a list of dicts ready to feed into ``MixtureComponent``.
    Position is assigned sequentially by the caller.
    """
    kinds = form_data.getlist("component_kind[]")
    ref_ids = form_data.getlist("component_ref_id[]")

    # Legacy fallback (pre-patch 14.6.7): single array of substance ids.
    legacy_sub_ids = form_data.getlist("component_substance_id[]")
    if not kinds and legacy_sub_ids:
        kinds = ["substance"] * len(legacy_sub_ids)
        ref_ids = legacy_sub_ids

    roles = form_data.getlist("component_role[]")
    concs = form_data.getlist("component_concentration[]")
    units = form_data.getlist("component_concentration_unit[]")
    notes = form_data.getlist("component_notes[]")

    # Pad shorter lists with empty strings — defensive against
    # partially-filled rows.
    n = max(
        len(kinds),
        len(ref_ids),
        len(roles),
        len(concs),
        len(units),
        len(notes),
    )
    kinds += [""] * (n - len(kinds))
    ref_ids += [""] * (n - len(ref_ids))
    roles += [""] * (n - len(roles))
    concs += [""] * (n - len(concs))
    units += [""] * (n - len(units))
    notes += [""] * (n - len(notes))

    rows: list[dict] = []
    for i in range(n):
        raw_ref = (ref_ids[i] or "").strip()
        if not raw_ref:
            continue  # skip empty rows
        try:
            ref_id = int(raw_ref)
        except (TypeError, ValueError):
            continue

        kind = (kinds[i] or "substance").strip()
        if kind not in ("substance", "mixture"):
            kind = "substance"

        role = (roles[i] or "solute").strip()
        if role not in COMPONENT_ROLES:
            role = "solute"

        # Concentration: parse if non-empty, else leave None
        raw_conc = (concs[i] or "").strip().replace(",", ".")
        try:
            conc = float(raw_conc) if raw_conc else None
        except ValueError:
            conc = None

        rows.append(
            {
                "kind": kind,
                "substance_id": ref_id if kind == "substance" else None,
                "child_mixture_id": ref_id if kind == "mixture" else None,
                "role": role,
                "concentration": conc,
                "concentration_unit": (units[i] or "").strip() or None,
                "notes": (notes[i] or "").strip() or None,
            }
        )
    return rows


def _apply_form_to_mixture(form: MixtureForm, mixture: Mixture, form_data):
    """Copy validated form data + component rows onto a Mixture.

    Pulled out to share between ``create`` and ``edit``. Doesn't
    commit — the caller does that after.
    """
    mixture.name = form.name.data
    mixture.kind = form.kind.data
    mixture.description = form.description.data or None
    mixture.primary_concentration = form.primary_concentration.data
    mixture.primary_concentration_unit = form.primary_concentration_unit.data or None

    # Primary solvent ID — coerce string to int|None
    raw_solvent = (form.primary_solvent_id.data or "").strip()
    try:
        mixture.primary_solvent_id = int(raw_solvent) if raw_solvent else None
    except (TypeError, ValueError):
        mixture.primary_solvent_id = None

    # GHS overrides:
    #   use_ghs_override checkbox unchecked → all override fields NULL
    #   checked → take whatever's in the multi-select / text inputs
    #     (an empty list is meaningful: it explicitly clears hazards)
    if form.use_ghs_override.data:
        mixture.ghs_pictograms_override = list(form.ghs_pictograms.data or [])
        mixture.h_phrases_override = _parse_phrase_codes(form.h_phrases_text.data or "")
        mixture.p_phrases_override = _parse_phrase_codes(form.p_phrases_text.data or "")
    else:
        mixture.ghs_pictograms_override = None
        mixture.h_phrases_override = None
        mixture.p_phrases_override = None

    mixture.notes = form.notes.data or None

    # Replace components wholesale. The orphan_delete cascade on the
    # relationship cleans up the old rows when we reassign the list.
    rows = _parse_component_rows(form_data)
    mixture.components = [
        MixtureComponent(
            substance_id=r["substance_id"],
            child_mixture_id=r["child_mixture_id"],
            role=r["role"],
            concentration=r["concentration"],
            concentration_unit=r["concentration_unit"],
            position=i,
            notes=r["notes"],
        )
        for i, r in enumerate(rows)
        # Defensive: skip rows where the child_mixture_id points at
        # the parent mixture itself. The dropdown filters this out
        # already, but a hand-crafted POST could still trigger it.
        if not (
            r["kind"] == "mixture"
            and mixture.id is not None
            and r["child_mixture_id"] == mixture.id
        )
    ]


# ── Routes ──────────────────────────────────────────────────────


@bp.route("/")
@login_required
def list_view():
    """List mixtures with live search.

    Search matches name, kind, description, and the names of
    constituent substances (so searching 'HCl' surfaces every
    mixture that contains HCl as a component, not just the ones
    named 'HCl …').
    """
    q = request.args.get("q", "").strip()
    show_inactive = request.args.get("show_inactive") == "1"

    query = db.session.query(Mixture)

    if not show_inactive:
        query = query.filter(Mixture.is_active.is_(True))

    if q:
        from sqlalchemy.orm import aliased

        like = f"%{q}%"
        comp = aliased(MixtureComponent)
        sub = aliased(Substance)
        query = (
            query.outerjoin(comp, comp.mixture_id == Mixture.id)
            .outerjoin(sub, sub.id == comp.substance_id)
            .filter(
                or_(
                    Mixture.name.ilike(like),
                    Mixture.kind.ilike(like),
                    Mixture.description.ilike(like),
                    sub.name.ilike(like),
                )
            )
            .distinct()
        )

    query = query.order_by(func.lower(Mixture.name).asc())
    mixtures = query.all()

    # HTMX partial: return only the table fragment
    if request.headers.get("HX-Request"):
        return render_template(
            "mixtures/_list_table.html",
            mixtures=mixtures,
            q=q,
        )

    return render_template(
        "mixtures/list.html",
        mixtures=mixtures,
        q=q,
        show_inactive=show_inactive,
    )


@bp.route("/<int:mixture_id>")
@login_required
def detail(mixture_id: int):
    m = db.session.get(Mixture, mixture_id)
    if m is None:
        abort(404)

    from flask_babel import get_locale

    locale = str(get_locale())
    # Show the EFFECTIVE hazards (override if set, else derived).
    h_phrases = _phrase_dict(m.effective_h_phrases, locale)
    p_phrases = _phrase_dict(m.effective_p_phrases, locale)

    log_event(action="read", entity_type="mixture", entity_id=m.id)

    # Notes + attachments — same pattern as substances detail
    from stoic_eln.services.attachments import list_attachments
    from stoic_eln.services.notes import list_notes

    notes_for_entity = list_notes("mixture", m.id)
    attachments_for_entity = list_attachments("mixture", m.id)

    return render_template(
        "mixtures/detail.html",
        mixture=m,
        h_phrases=h_phrases,
        p_phrases=p_phrases,
        notes_for_entity=notes_for_entity,
        attachments_for_entity=attachments_for_entity,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@supervisor_required
def create():
    form = MixtureForm()
    if form.validate_on_submit():
        m = Mixture()
        _apply_form_to_mixture(form, m, request.form)
        db.session.add(m)
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001 — broad to surface all DB errors
            db.session.rollback()
            logger.exception("Failed to create mixture")
            flash(_("Errore durante il salvataggio"), "danger")
            return render_template("mixtures/form.html", form=form, mixture=None)

        log_event(action="create", entity_type="mixture", entity_id=m.id)
        flash(_("Miscela creata"), "success")
        return redirect(url_for("mixtures.detail", mixture_id=m.id))

    return render_template("mixtures/form.html", form=form, mixture=None)


@bp.route("/<int:mixture_id>/edit", methods=["GET", "POST"])
@login_required
@supervisor_required
def edit(mixture_id: int):
    m = db.session.get(Mixture, mixture_id)
    if m is None:
        abort(404)

    form = MixtureForm(obj=m)

    # Pre-populate the override checkbox + fields from the current
    # state. When the user lands on edit, the override toggle reflects
    # whether the mixture currently HAS overrides; the multi-select
    # and text fields show the override values (or empty if no
    # override).
    if request.method == "GET":
        has_override = (
            m.ghs_pictograms_override is not None
            or m.h_phrases_override is not None
            or m.p_phrases_override is not None
        )
        form.use_ghs_override.data = has_override
        if has_override:
            form.ghs_pictograms.data = m.ghs_pictograms_override or []
            form.h_phrases_text.data = ", ".join(m.h_phrases_override or [])
            form.p_phrases_text.data = ", ".join(m.p_phrases_override or [])
        form.primary_solvent_id.data = str(m.primary_solvent_id) if m.primary_solvent_id else ""

    if form.validate_on_submit():
        _apply_form_to_mixture(form, m, request.form)
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()
            logger.exception("Failed to update mixture %s", mixture_id)
            flash(_("Errore durante il salvataggio"), "danger")
            return render_template("mixtures/form.html", form=form, mixture=m)

        log_event(action="update", entity_type="mixture", entity_id=m.id)
        flash(_("Miscela aggiornata"), "success")
        return redirect(url_for("mixtures.detail", mixture_id=m.id))

    return render_template("mixtures/form.html", form=form, mixture=m)


@bp.route("/<int:mixture_id>/delete", methods=["POST"])
@login_required
@supervisor_required
def delete(mixture_id: int):
    """Soft-delete a mixture (sets is_active=False).

    Refuses if the mixture has active inventory items — ask the user
    to deactivate the lots first. Hard-deletion isn't exposed in the
    UI; if you really need it, do it in a DB shell.
    """
    m = db.session.get(Mixture, mixture_id)
    if m is None:
        abort(404)

    active_lots = [it for it in m.inventory_items if it.is_active]
    if active_lots:
        flash(
            _("Non posso disattivare: ci sono lotti attivi (%(n)d)", n=len(active_lots)),
            "warning",
        )
        return redirect(url_for("mixtures.detail", mixture_id=m.id))

    m.is_active = False
    db.session.commit()
    log_event(action="deactivate", entity_type="mixture", entity_id=m.id)
    flash(_("Miscela disattivata"), "info")
    return redirect(url_for("mixtures.list_view"))


# ── Component picker autocomplete ────────────────────────────────


@bp.route("/api/substance_picker")
@login_required
def substance_picker():
    """Lightweight endpoint for the component-row picker.

    Returns active substances matching ``q`` as JSON. Used by the
    JS in the form to populate the autocomplete dropdown.
    """
    q = request.args.get("q", "").strip()
    query = db.session.query(Substance).filter(Substance.is_active.is_(True))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Substance.name.ilike(like),
                Substance.iupac_name.ilike(like),
                Substance.molecular_formula.ilike(like),
                Substance.cas_number.ilike(like),
            )
        )
    rows = query.order_by(func.lower(Substance.name)).limit(20).all()
    return {
        "results": [
            {
                "id": s.id,
                "name": s.name,
                "formula": s.molecular_formula or "",
                "cas": s.cas_number or "",
            }
            for s in rows
        ],
    }


@bp.route("/api/mixture_picker")
@login_required
def mixture_picker():
    """Lightweight endpoint for the mixture-as-component picker.

    Returns mixtures matching ``q`` as JSON. Used by the JS in the
    form when the user picks "Miscela" for a component row (e.g.
    "HCl 6N has HCl 12N as a solute-equivalent component").

    The optional ``exclude_id`` parameter takes a mixture id to
    omit from results — the route passes the *current* mixture's
    id so the user can't accidentally pick the same mixture as
    its own component (would create a 1-hop cycle). Deeper cycles
    aren't prevented here; the model's derived properties have a
    visited-set guard for that.
    """
    q = request.args.get("q", "").strip()
    raw_exclude = request.args.get("exclude_id", "").strip()
    exclude_id: int | None = None
    if raw_exclude:
        try:
            exclude_id = int(raw_exclude)
        except ValueError:
            exclude_id = None

    query = db.session.query(Mixture)
    if exclude_id is not None:
        query = query.filter(Mixture.id != exclude_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Mixture.name.ilike(like),
                Mixture.description.ilike(like),
            )
        )
    rows = query.order_by(func.lower(Mixture.name)).limit(20).all()
    return {
        "results": [
            {
                "id": m.id,
                "name": m.display_label,
                "kind": m.kind,
            }
            for m in rows
        ],
    }


# ── Preparation flow ─────────────────────────────────────────────


@bp.route("/<int:mixture_id>/prepare", methods=["GET"])
@login_required
@supervisor_required
def prepare_form(mixture_id: int):
    """Show the 'Prepare a new lot' form for a mixture.

    Two phases on the same template:

    * **Phase 1** (default — no querystring): operator picks target
      quantity + unit; we render a small form with just those fields.
    * **Phase 2** (when ``?target_quantity=…&target_unit=…`` is set):
      we run ``suggest_consumptions`` and render the per-component
      table where each row carries a lot picker + a quantity field
      pre-populated with the suggestion. Operator confirms or
      modifies, then submits to the ``execute_prep`` POST endpoint.

    The two-phase pattern keeps the URL representable and bookmarkable
    for QA: pasting "/mixtures/5/prepare?target_quantity=4&target_unit=L"
    re-runs the suggestion deterministically.
    """
    m = db.session.get(Mixture, mixture_id)
    if m is None:
        abort(404)

    raw_qty = request.args.get("target_quantity", "").strip().replace(",", ".")
    target_unit = request.args.get("target_unit", "").strip()
    target_quantity: float | None = None
    try:
        target_quantity = float(raw_qty) if raw_qty else None
    except ValueError:
        target_quantity = None

    suggestion = None
    if target_quantity is not None and target_quantity > 0 and target_unit:
        suggestion = suggest_consumptions(
            mixture=m,
            target_quantity=target_quantity,
            target_unit=target_unit,
        )

    # Preview of the auto-generated batch code (operator can override
    # in the form).
    from stoic_eln.services.prep_code import (
        generate_prep_code,
    )

    preview_code = ""
    if suggestion is not None:
        try:
            preview_code, _seq = generate_prep_code(
                mixture_name=m.name,
                mixture_id=m.id,
            )
        except Exception:  # noqa: BLE001 — preview is best-effort
            logger.exception("Failed to preview prep code")
            preview_code = ""

    # Suggested default expiry for the output lot: earliest expiry
    # among the active lots of the precursor substances/mixtures.
    # The operator can edit; we just save them the math.
    suggested_expiry = m.suggested_expiry_date()

    return render_template(
        "mixtures/prepare.html",
        mixture=m,
        target_quantity=target_quantity,
        target_unit=target_unit,
        suggestion=suggestion,
        preview_code=preview_code,
        suggested_expiry=suggested_expiry,
    )


@bp.route("/<int:mixture_id>/prepare", methods=["POST"])
@login_required
@supervisor_required
def execute_prep(mixture_id: int):
    """Execute a preparation submitted from ``prepare_form``.

    Body fields:

    * ``target_quantity``, ``target_unit`` — final target.
    * ``consumption_lot_id[]``, ``consumption_quantity[]``,
      ``consumption_unit[]`` — parallel arrays, one entry per row
      the operator confirmed. Empty rows (no lot selected, or qty
      zero) are skipped here.
    * ``output_batch_code`` — if blank, auto-generated server-side.
    * ``output_location``, ``output_expiry_date``, ``output_notes``
      — passed through to the new lot.
    """
    m = db.session.get(Mixture, mixture_id)
    if m is None:
        abort(404)

    f = request.form
    try:
        target_qty = float((f.get("target_quantity") or "0").replace(",", "."))
    except ValueError:
        flash(_("Quantità target non valida."), "danger")
        return redirect(
            url_for(
                "mixtures.prepare_form",
                mixture_id=mixture_id,
            )
        )
    target_unit = (f.get("target_unit") or "").strip()

    lot_ids = f.getlist("consumption_lot_id[]")
    qtys = f.getlist("consumption_quantity[]")
    units = f.getlist("consumption_unit[]")

    consumptions: list[ConsumptionInput] = []
    n = max(len(lot_ids), len(qtys), len(units))
    lot_ids += [""] * (n - len(lot_ids))
    qtys += [""] * (n - len(qtys))
    units += [""] * (n - len(units))

    for i in range(n):
        raw_lot = (lot_ids[i] or "").strip()
        if not raw_lot:
            continue
        raw_qty = (qtys[i] or "").strip().replace(",", ".")
        try:
            qty = float(raw_qty)
        except ValueError:
            continue
        if qty <= 0:
            continue
        try:
            consumptions.append(
                ConsumptionInput(
                    inventory_item_id=int(raw_lot),
                    quantity_consumed=qty,
                    quantity_unit=(units[i] or "mL").strip(),
                )
            )
        except (TypeError, ValueError):
            continue

    if not consumptions:
        flash(
            _("Nessun lotto precursore selezionato. Seleziona almeno uno."),
            "warning",
        )
        return redirect(
            url_for(
                "mixtures.prepare_form",
                mixture_id=mixture_id,
                target_quantity=target_qty,
                target_unit=target_unit,
            )
        )

    inp = PrepInput(
        mixture_id=m.id,
        target_quantity=target_qty,
        target_quantity_unit=target_unit,
        consumptions=consumptions,
        output_batch_code=(f.get("output_batch_code") or "").strip() or None,
        output_location=(f.get("output_location") or "").strip() or None,
        output_expiry_date=(f.get("output_expiry_date") or "").strip() or None,
        output_notes=(f.get("output_notes") or "").strip() or None,
        prepared_by_id=getattr(current_user, "id", None),
    )

    try:
        prep = execute_preparation(inp)
    except ValueError as e:
        # Validation failure (lot empty, quantity exceeds available, …).
        # The service rolled back already; surface the error.
        flash(str(e), "danger")
        return redirect(
            url_for(
                "mixtures.prepare_form",
                mixture_id=mixture_id,
                target_quantity=target_qty,
                target_unit=target_unit,
            )
        )
    except Exception:  # noqa: BLE001
        db.session.rollback()
        logger.exception("Failed to execute preparation")
        flash(_("Errore imprevisto durante la preparazione."), "danger")
        return redirect(
            url_for(
                "mixtures.prepare_form",
                mixture_id=mixture_id,
                target_quantity=target_qty,
                target_unit=target_unit,
            )
        )

    log_event(
        action="create",
        entity_type="mixture_prep",
        entity_id=prep.id,
        details={
            "mixture_id": m.id,
            "target_quantity": target_qty,
            "target_unit": target_unit,
            "output_lot_id": prep.output_inventory_item_id,
        },
    )
    flash(
        _("Preparazione completata: lotto %(code)s", code=prep.code),
        "success",
    )
    # Redirect to the new lot's detail (which is an InventoryItem)
    return redirect(
        url_for(
            "inventory.edit",
            item_id=prep.output_inventory_item_id,
        )
    )


# ── HTMX: recompute consumption row when lot changes ────────────


@bp.route("/<int:mixture_id>/prepare/recompute_row", methods=["POST"])
@login_required
def recompute_prep_row(mixture_id: int):
    """Recompute one consumption row given a newly-selected lot.

    Body fields:
      * ``component_id`` — the MixtureComponent.id this row maps to
      * ``lot_id``       — the InventoryItem.id the operator just picked
      * ``target_quantity``, ``target_unit`` — current target

    Returns the HTML fragment for the row (the inputs for lot picker,
    quantity, unit, plus the "stock conc: X" hint). The template
    re-renders the row with the new auto-suggested quantity given
    the freshly-chosen stock concentration.

    This is the "auto-detect with confirmation on screen" behaviour:
    when you swap from a 12N stock lot to a 6N stock lot, the
    quantity field updates AND the "stock conc" line below updates.
    """
    m = db.session.get(Mixture, mixture_id)
    if m is None:
        abort(404)

    f = request.form
    try:
        component_id = int(f.get("component_id") or 0)
        lot_id = int(f.get("lot_id") or 0) if (f.get("lot_id") or "").strip() else None
        target_quantity = float((f.get("target_quantity") or "0").replace(",", "."))
    except ValueError:
        abort(400)
    target_unit = (f.get("target_unit") or "").strip() or "L"

    comp = db.session.get(MixtureComponent, component_id)
    if comp is None or comp.mixture_id != m.id:
        abort(404)

    # Always recompute the FULL suggestion (cheap, and lets us
    # leverage the existing strategy detection — including the
    # "if I change one stock, the dilution math reflows for the
    # whole mixture" case).
    suggestion = suggest_consumptions(
        mixture=m,
        target_quantity=target_quantity,
        target_unit=target_unit,
    )

    # If the operator picked a specific lot that isn't the
    # default suggestion, re-compute solute quantity using THAT
    # lot's stock concentration. We do this only for the solute
    # component(s) — the solvent's amount follows from the target
    # volume minus the solute volume.
    if lot_id is not None and comp.role == "solute":
        from stoic_eln.services.prep_service import (
            read_stock_for_solute,
            _normalize_concentration,
            _are_dilution_compatible,
            _normalize_to_mL,
        )

        chosen_lot = db.session.get(InventoryItem, lot_id)
        if (
            chosen_lot is not None
            and m.primary_concentration is not None
            and m.primary_concentration_unit
        ):
            stock_info = read_stock_for_solute(chosen_lot, comp.substance_id)
            if (
                stock_info.concentration is not None
                and stock_info.unit
                and _are_dilution_compatible(
                    stock_info.unit,
                    m.primary_concentration_unit,
                )
            ):
                c_target = _normalize_concentration(
                    m.primary_concentration,
                    m.primary_concentration_unit,
                )
                c_stock = _normalize_concentration(
                    stock_info.concentration,
                    stock_info.unit,
                )
                if c_target is not None and c_stock and c_stock > 0:
                    ratio = c_target / c_stock
                    v_target_mL = _normalize_to_mL(target_quantity, target_unit)
                    solute_mL = v_target_mL * ratio
                    # Update the rows in-place
                    for r in suggestion.rows:
                        if r.component_id == component_id:
                            if target_unit == "L":
                                r.suggested_quantity = solute_mL / 1000.0
                                r.suggested_unit = "L"
                            else:
                                r.suggested_quantity = solute_mL
                                r.suggested_unit = "mL"
                            r.suggested_lot_id = lot_id
                            r.stock_info = stock_info
                        elif r.role != "solute":
                            # Solvent picks up the rest
                            other_mL = max(0.0, v_target_mL - solute_mL)
                            if target_unit == "L":
                                r.suggested_quantity = other_mL / 1000.0
                                r.suggested_unit = "L"
                            else:
                                r.suggested_quantity = other_mL
                                r.suggested_unit = "mL"

    return render_template(
        "mixtures/_prep_rows.html",
        suggestion=suggestion,
        mixture=m,
    )
