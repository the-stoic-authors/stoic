"""Stoic ELN — Run routes.

Endpoints:
  GET  /runs/                   — history list (TODO Settimana 4 step 5)
  GET  /runs/<id>                — run detail (setup page if draft,
                                  execution page if in_progress,
                                  read-only page if completed)
  POST /runs/<id>/scale          — update scale_mmol + recompute targets
  POST /runs/<id>/component/<cid>/lot       — set inventory lot
  POST /runs/<id>/component/<cid>/actual    — set actual mass/volume
  POST /runs/<id>/checklist/<cid>/toggle    — toggle a checkbox
  POST /runs/<id>/start          — validate + deduct + transition
  POST /runs/<id>/complete       — input yield, transition to completed
  POST /runs/<id>/notes_post     — append post-completion notes (always allowed)
  POST /runs/<id>/cancel         — delete a draft run

Plus a helper:
  POST /reactions/<id>/run/start — create a fresh draft and redirect
                                  to its setup page (called from the
                                  "Esegui run" button on a template).
"""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from stoic_eln.blueprints.runs import bp
from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.run import (
    STATUS_IN_PROGRESS,
    Run,
)
from stoic_eln.models.run_component import RunComponent
from stoic_eln.models.run_step import RunChecklistItem
from stoic_eln.services import run_setup


# ─── List ────────────────────────────────────────────────────────────────


@bp.route("/", methods=["GET"])
@login_required
def list_view():
    """List all runs, most recent first."""
    runs = db.session.query(Run).order_by(Run.created_at.desc()).all()
    # Compute cost per run for the cost column. We do this in Python since
    # the cost is a derived calculation across multiple tables.
    from stoic_eln.services.run_cost import compute_run_cost

    run_costs = {r.id: compute_run_cost(r) for r in runs}
    return render_template("runs/list.html", runs=runs, run_costs=run_costs)


# ─── Detail / setup / execution ─────────────────────────────────────────


@bp.route("/<int:run_id>", methods=["GET"])
@login_required
def detail(run_id: int):
    """Render the right page based on the run's status."""
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    from stoic_eln.services.run_cost import (
        compute_run_cost,
        product_unit_metrics,
    )

    cost_breakdown = compute_run_cost(run)
    metrics_cumulative = product_unit_metrics(run, cost_breakdown.total_eur)
    metrics_direct = product_unit_metrics(run, cost_breakdown.direct_total_eur)

    # Notes (Settimana 6 patch 9)
    from stoic_eln.services.notes import list_notes

    notes_for_entity = list_notes("run", run.id)

    # Attachments (Settimana 6 patch 10)
    from stoic_eln.services.attachments import list_attachments

    attachments_for_entity = list_attachments("run", run.id)

    return render_template(
        "runs/detail.html",
        run=run,
        cost_breakdown=cost_breakdown,
        metrics_cumulative=metrics_cumulative,
        metrics_direct=metrics_direct,
        notes_for_entity=notes_for_entity,
        attachments_for_entity=attachments_for_entity,
    )


# ─── Mutations on a draft run ───────────────────────────────────────────


def _ensure_draft(run: Run) -> None:
    if not run.is_draft:
        flash(_("Questa azione non è permessa: il run non è più in bozza."), "warning")
        return False
    return True


@bp.route("/<int:run_id>/scale", methods=["POST"])
@login_required
def update_scale(run_id: int):
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if not _ensure_draft(run):
        return redirect(url_for("runs.detail", run_id=run_id))

    raw = (
        (request.form.get("scale_amount") or request.form.get("scale_mmol") or "")
        .strip()
        .replace(",", ".")
    )
    unit = (request.form.get("scale_unit") or "mmol").strip()

    if raw == "":
        # Clearing the scale
        run.scale_mmol = None
        run.scale_input_value = None
        run.scale_input_unit = None
        run_setup.recompute_targets(run)
        db.session.commit()
        return redirect(url_for("runs.detail", run_id=run_id))

    try:
        amount = float(raw)
    except ValueError:
        flash(_("Scala non valida."), "danger")
        return redirect(url_for("runs.detail", run_id=run_id))

    if amount <= 0:
        flash(_("La scala deve essere maggiore di zero."), "danger")
        return redirect(url_for("runs.detail", run_id=run_id))

    # Find the limiting reagent's substance for mass/volume conversions
    from stoic_eln.services import units

    limiting_comp = next((c for c in run.components if c.is_limiting), None)
    sub = limiting_comp.substance if limiting_comp else None

    try:
        run.scale_mmol = units.parse_scale_to_mmol(amount, unit, substance=sub)
    except units.ScaleConversionError as e:
        flash(str(e), "danger")
        return redirect(url_for("runs.detail", run_id=run_id))

    # Remember the exact input so the UI can re-display it as entered.
    run.scale_input_value = amount
    run.scale_input_unit = unit

    run_setup.recompute_targets(run)
    db.session.commit()
    return redirect(url_for("runs.detail", run_id=run_id))


@bp.route("/<int:run_id>/component/<int:cid>/lot", methods=["POST"])
@login_required
def set_lot(run_id: int, cid: int):
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if not _ensure_draft(run):
        return redirect(url_for("runs.detail", run_id=run_id))

    rc = db.session.get(RunComponent, cid)
    if rc is None or rc.run_id != run_id:
        abort(404)

    raw = (request.form.get("lot_id") or "").strip()
    if not raw:
        rc.inventory_item_id = None
    else:
        try:
            lot_id = int(raw)
        except ValueError:
            flash(_("Lotto non valido."), "danger")
            return redirect(url_for("runs.detail", run_id=run_id))
        lot = db.session.get(InventoryItem, lot_id)
        if lot is None:
            flash(_("Lotto non trovato."), "danger")
            return redirect(url_for("runs.detail", run_id=run_id))
        # Lot must match the component's kind:
        #   substance-backed component → lot.substance_id matches
        #   mixture-backed component   → lot.mixture_id matches
        # The XOR constraint on InventoryItem guarantees the lot
        # has exactly one of the two set, so we just compare the
        # appropriate one against the run component.
        if rc.mixture_id is not None:
            if lot.mixture_id != rc.mixture_id:
                flash(_("Lotto non corrisponde alla miscela."), "danger")
                return redirect(url_for("runs.detail", run_id=run_id))
        else:
            if lot.substance_id != rc.substance_id:
                flash(_("Lotto non corrisponde alla sostanza."), "danger")
                return redirect(url_for("runs.detail", run_id=run_id))
        rc.inventory_item_id = lot_id

    db.session.commit()

    if request.headers.get("HX-Request"):
        return ("", 204)
    return redirect(url_for("runs.detail", run_id=run_id))


@bp.route("/<int:run_id>/component/<int:cid>/actual", methods=["POST"])
@login_required
def set_actual(run_id: int, cid: int):
    """Set the actual measured mass or volume.

    For non-product components, only allowed when run is in ``draft``
    (you set the inputs you'll pour in BEFORE pressing Avvia, which
    deducts inventory). For products, also allowed during ``in_progress``
    so the operator can record the isolated yield before completing.
    """
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)

    rc = db.session.get(RunComponent, cid)
    if rc is None or rc.run_id != run_id:
        abort(404)

    is_product = rc.role in ("product", "byproduct")
    if run.is_completed:
        flash(_("Run completato: non si possono più modificare i pesi."), "warning")
        return redirect(url_for("runs.detail", run_id=run_id))
    if run.is_in_progress and not is_product:
        flash(
            _("Run in esecuzione: solo i pesi dei prodotti possono ancora essere inseriti."),
            "warning",
        )
        return redirect(url_for("runs.detail", run_id=run_id))

    raw = (request.form.get("actual") or "").strip().replace(",", ".")
    unit = (request.form.get("unit") or "").strip()

    if raw == "":
        rc.actual_mass_g = None
        rc.actual_volume_mL = None
        db.session.commit()
        if request.headers.get("HX-Request"):
            return ("", 204)
        return redirect(url_for("runs.detail", run_id=run_id))

    try:
        amount = float(raw)
    except ValueError:
        flash(_("Quantità non valida."), "danger")
        return redirect(url_for("runs.detail", run_id=run_id))

    from stoic_eln.services import units

    # Determine which channel (mass or volume) and convert to canonical
    if unit in ("mg", "g"):
        rc.actual_mass_g = units.to_grams(amount, unit)
        rc.actual_volume_mL = None
    elif unit in ("mL", "L"):
        rc.actual_volume_mL = units.to_mL(amount, unit)
        rc.actual_mass_g = None
    else:
        # Fallback to target's unit class
        if rc.is_solvent or rc.target_volume_mL is not None:
            rc.actual_volume_mL = amount
            rc.actual_mass_g = None
        else:
            rc.actual_mass_g = amount
            rc.actual_volume_mL = None

    db.session.commit()

    if request.headers.get("HX-Request"):
        # Auto-save: no UI update needed beyond the input itself.
        # Return 204 No Content so HTMX doesn't try to swap anything.
        return ("", 204)
    return redirect(url_for("runs.detail", run_id=run_id))


# ─── Step components: lot + actual quantity (Settimana 6 patch 7) ──


@bp.route("/<int:run_id>/step_component/<int:scid>/lot", methods=["POST"])
@login_required
def set_step_lot(run_id: int, scid: int):
    """Assign an inventory lot to a workup/step component."""
    from stoic_eln.models.run_step import RunStepComponent

    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if run.is_completed:
        flash(_("Run completato: non si possono modificare i lotti."), "warning")
        return redirect(url_for("runs.detail", run_id=run_id))

    sc = db.session.get(RunStepComponent, scid)
    if sc is None or sc.step.run_id != run_id:
        abort(404)

    raw = (request.form.get("lot_id") or "").strip()
    if not raw:
        sc.inventory_item_id = None
    else:
        try:
            lot_id = int(raw)
        except ValueError:
            flash(_("Lotto non valido."), "danger")
            return redirect(url_for("runs.detail", run_id=run_id))
        lot = db.session.get(InventoryItem, lot_id)
        if lot is None:
            flash(_("Lotto non trovato."), "danger")
            return redirect(url_for("runs.detail", run_id=run_id))
        # Lot kind must match component kind: same XOR validation as
        # set_lot for main components (patch 13.5/13.6).
        if sc.mixture_id is not None:
            if lot.mixture_id != sc.mixture_id:
                flash(_("Lotto non corrisponde alla miscela."), "danger")
                return redirect(url_for("runs.detail", run_id=run_id))
        else:
            if lot.substance_id != sc.substance_id:
                flash(_("Lotto non corrisponde alla sostanza."), "danger")
                return redirect(url_for("runs.detail", run_id=run_id))
        sc.inventory_item_id = lot_id

    db.session.commit()
    if request.headers.get("HX-Request"):
        return ("", 204)
    return redirect(url_for("runs.detail", run_id=run_id))


@bp.route("/<int:run_id>/step_component/<int:scid>/actual", methods=["POST"])
@login_required
def set_step_actual(run_id: int, scid: int):
    """Record the actual quantity used in a workup/step component.

    Unlike main reaction components, step quantities are often
    "free": you don't know in advance how much DCM you'll use for the
    column — you measure it after the fact. So this is allowed
    during ``draft`` AND ``in_progress`` (any state but completed).
    """
    from stoic_eln.models.run_step import RunStepComponent

    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if run.is_completed:
        flash(_("Run completato: non si possono modificare le quantità."), "warning")
        return redirect(url_for("runs.detail", run_id=run_id))

    sc = db.session.get(RunStepComponent, scid)
    if sc is None or sc.step.run_id != run_id:
        abort(404)

    raw = (request.form.get("actual") or "").strip().replace(",", ".")
    unit = (request.form.get("unit") or "").strip()

    if raw == "":
        sc.actual_mass_g = None
        sc.actual_volume_mL = None
        db.session.commit()
        if request.headers.get("HX-Request"):
            return ("", 204)
        return redirect(url_for("runs.detail", run_id=run_id))

    try:
        amount = float(raw)
    except ValueError:
        flash(_("Quantità non valida."), "danger")
        return redirect(url_for("runs.detail", run_id=run_id))

    from stoic_eln.services import units

    if unit in ("mg", "g"):
        sc.actual_mass_g = units.to_grams(amount, unit)
        sc.actual_volume_mL = None
    elif unit in ("mL", "L"):
        sc.actual_volume_mL = units.to_mL(amount, unit)
        sc.actual_mass_g = None
    else:
        # Fall back: mixtures are always liquid (volumetric);
        # for substance, liquids get mL, solids get g.
        if sc.mixture_id is not None:
            sc.actual_volume_mL = amount
            sc.actual_mass_g = None
        else:
            sub = sc.substance
            if sub and sub.state == "liquid":
                sc.actual_volume_mL = amount
                sc.actual_mass_g = None
            else:
                sc.actual_mass_g = amount
                sc.actual_volume_mL = None

    db.session.commit()
    if request.headers.get("HX-Request"):
        return ("", 204)
    return redirect(url_for("runs.detail", run_id=run_id))


@bp.route("/<int:run_id>/step-parameter/<int:pid>", methods=["POST"])
@login_required
def set_step_parameter(run_id: int, pid: int):
    """Record the operator's value for a step parameter (P3).

    Stored as free text (the unit lives on the parameter), so ranges
    like ``65-68`` or notes are fine. Allowed while draft/in-progress,
    blocked once the run is completed. HTMX-friendly (204, no swap).
    """
    from stoic_eln.models.run_step import RunStepParameter

    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if run.is_completed:
        flash(_("Run completato: non si possono modificare i parametri."), "warning")
        return redirect(url_for("runs.detail", run_id=run_id))

    prm = db.session.get(RunStepParameter, pid)
    if prm is None or prm.step.run_id != run_id:
        abort(404)

    raw = (request.form.get("value") or "").strip()
    prm.value = raw or None
    db.session.commit()

    if request.headers.get("HX-Request"):
        return ("", 204)
    return redirect(url_for("runs.detail", run_id=run_id))


@bp.route("/<int:run_id>/checklist/<int:cid>/toggle", methods=["POST"])
@login_required
def toggle_checklist(run_id: int, cid: int):
    """Toggle a run-level checklist item.

    If the request is HTMX, return the single ``<li>`` re-rendered so
    the page doesn't reload (and the scroll position is preserved).
    """
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if run.is_completed:
        flash(_("Run completato: la check list non è più modificabile."), "warning")
        return redirect(url_for("runs.detail", run_id=run_id))

    item = db.session.get(RunChecklistItem, cid)
    if item is None:
        abort(404)
    # Item must belong to this run (directly or via one of its steps)
    own = item.run_id == run_id or (item.step and item.step.run_id == run_id)
    if not own:
        abort(404)

    item.is_done = not item.is_done
    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template(
            "runs/_checklist_item.html",
            item=item,
            run=run,
        )
    return redirect(url_for("runs.detail", run_id=run_id))


# ─── Lifecycle transitions ──────────────────────────────────────────────


@bp.route("/<int:run_id>/start", methods=["POST"])
@login_required
def start(run_id: int):
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if not _ensure_draft(run):
        return redirect(url_for("runs.detail", run_id=run_id))

    try:
        run_setup.start_run(run)
    except run_setup.RunStartError as e:
        for err in e.errors:
            flash(err, "danger")
        return redirect(url_for("runs.detail", run_id=run_id))

    db.session.commit()
    flash(_("Run avviato. Inventario aggiornato."), "success")
    return redirect(url_for("runs.detail", run_id=run_id))


@bp.route("/<int:run_id>/complete", methods=["POST"])
@login_required
def complete(run_id: int):
    """Complete a run.

    Reads the product weights directly from RunComponent.actual_mass_g
    (set by the operator during in_progress). If no product has a mass,
    the form must include ``confirm_failed=1`` to acknowledge that the
    run will be recorded as failed.

    Optional notes can be appended via ``notes``.
    """
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if run.status != STATUS_IN_PROGRESS:
        flash(_("Solo i run in esecuzione possono essere completati."), "warning")
        return redirect(url_for("runs.detail", run_id=run_id))

    notes = (request.form.get("notes") or "").strip()
    if notes:
        run.notes = notes

    confirm_failed = (request.form.get("confirm_failed") or "").strip() == "1"

    try:
        result = run_setup.complete_run(run, force_no_products=confirm_failed)
    except run_setup.RunStartError as e:
        # Products without weight: bounce back with a flag so the
        # template can show the confirmation dialog.
        for err in e.errors:
            flash(err, "warning")
        return redirect(url_for("runs.detail", run_id=run_id, _anchor="confirm-no-products"))

    db.session.commit()

    # Surface any warnings and the auto-created lots
    if "yield_over_100" in result["warnings"]:
        flash(
            _(
                "Resa > 100%% (%(p).1f%%): possibile errore di pesata o "
                "sale idrato. Salvato comunque.",
                p=result["yield_percent"] or 0,
            ),
            "warning",
        )

    for lot in result["lots_created"]:
        flash(
            _(
                "Creato lotto %(code)s: %(qty).3f g di %(name)s.",
                code=lot["batch_code"],
                qty=lot["quantity_g"],
                name=lot["product_name"],
            ),
            "success",
        )

    if result["is_failed"]:
        flash(_("Run registrato come fallito (resa zero)."), "info")
    else:
        flash(_("Run completato."), "success")

    return redirect(url_for("runs.detail", run_id=run_id))


@bp.route("/<int:run_id>/notes_post", methods=["POST"])
@login_required
def append_post_notes(run_id: int):
    """Append post-completion notes (always allowed for completed runs)."""
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if not run.is_completed:
        flash(_("Le note post-mortem si aggiungono solo a run completati."), "warning")
        return redirect(url_for("runs.detail", run_id=run_id))

    text = (request.form.get("text") or "").strip()
    if text:
        run.post_completion_notes = text  # last-write-wins
        db.session.commit()
        flash(_("Note aggiornate."), "success")
    return redirect(url_for("runs.detail", run_id=run_id))


@bp.route("/<int:run_id>/cancel", methods=["POST"])
@login_required
def cancel(run_id: int):
    """Delete a draft run."""
    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)
    if not run.is_draft:
        flash(_("Solo le bozze possono essere annullate."), "warning")
        return redirect(url_for("runs.detail", run_id=run_id))

    rxn_id = run.reaction_id
    db.session.delete(run)
    db.session.commit()
    flash(_("Bozza di run eliminata."), "info")
    return redirect(url_for("reactions.detail", reaction_id=rxn_id))


# ─── Entry point: create from a template ────────────────────────────────


@bp.route("/from/<int:reaction_id>", methods=["POST"])
@login_required
def create_from_template(reaction_id: int):
    """Create a new draft run from a published template and redirect."""
    rxn = db.session.get(Reaction, reaction_id)
    if rxn is None:
        abort(404)
    if rxn.status != "published":
        flash(_("Puoi eseguire solo template pubblicati."), "warning")
        return redirect(url_for("reactions.detail", reaction_id=reaction_id))

    try:
        run = run_setup.create_draft(rxn, current_user)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("reactions.detail", reaction_id=reaction_id))

    db.session.commit()
    flash(_("Bozza di run creata: %(code)s.", code=run.code), "success")
    return redirect(url_for("runs.detail", run_id=run.id))


# ─── PDF reports (Settimana 5) ──────────────────────────────────────────


@bp.route("/<int:run_id>/pdf", methods=["GET"])
@login_required
def pdf(run_id: int):
    """Download a PDF report of this run.

    Query string:
      type=summary  → 1-page synthesis (default)
      type=full     → multi-page complete protocol with scheme & steps
    """
    from flask import send_file

    run = db.session.get(Run, run_id)
    if run is None:
        abort(404)

    pdf_type = (request.args.get("type") or "summary").lower()

    from stoic_eln.services.pdf_run import render_run_summary, render_run_full

    if pdf_type == "full":
        data = render_run_full(run)
        suffix = "completo"
    else:
        data = render_run_summary(run)
        suffix = "sintesi"

    safe_code = (run.code or f"run-{run.id}").replace("/", "-")
    filename = f"{safe_code}-{suffix}.pdf"

    from stoic_eln.services.audit import log_event

    log_event(
        action="download_run_pdf", entity_type="run", entity_id=run.id, details={"type": pdf_type}
    )

    from io import BytesIO

    return send_file(
        BytesIO(data),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=filename,
    )


# ─── Settimana 6 patch 6 — Pagina statistiche globale ─────────────


@bp.route("/stats", methods=["GET"])
@login_required
def stats():
    """Lab-wide overview: stats per template across all runs."""
    from stoic_eln.services.template_stats import all_templates_stats

    all_stats = all_templates_stats()
    # Total run count
    total_runs = sum(s.n_runs for s in all_stats)
    total_cost = sum(s.avg_cost_eur * s.n_runs for s in all_stats if s.avg_cost_eur is not None)
    return render_template(
        "runs/stats.html",
        all_stats=all_stats,
        total_runs=total_runs,
        total_cost=total_cost,
    )
