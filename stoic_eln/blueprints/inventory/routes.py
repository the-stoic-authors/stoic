"""Stoic ELN — Inventory routes."""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import or_

from stoic_eln.blueprints.inventory import bp
from stoic_eln.blueprints._decorators import supervisor_required
from stoic_eln.blueprints.inventory.forms import InventoryItemForm
from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.substance import Substance
from stoic_eln.services.audit import log_event


@bp.route("/")
@login_required
def list_view():
    """Warehouse view: all lots with filters + sort."""
    from datetime import date as _date, timedelta
    from sqlalchemy import case, func

    q = request.args.get("q", "").strip()
    status = request.args.get("status", "all").lower()
    kind = request.args.get("kind", "all").lower()
    group_filter = request.args.get("group", "").strip()
    supplier_filter = request.args.get("supplier", "").strip()
    sort = request.args.get("sort", "substance").lower()
    direction = request.args.get("direction", "asc").lower()
    show_inactive = request.args.get("show_inactive") == "1"

    # Validate kind: substance | mixture | solvent | all
    # - 'substance': all substance lots, including solvents
    # - 'mixture': only mixture lots
    # - 'solvent': strict subset of substance lots where
    #   substance.is_solvent is True. Mixtures have no equivalent
    #   flag, so they are excluded when filtering by solvent.
    # - 'all': no kind restriction
    if kind not in ("all", "substance", "mixture", "solvent"):
        kind = "all"

    # Validate sort key. The substance/mixture name is a polymorphic
    # field — coalesce across the two tables so a single sort key
    # works for both lot kinds.
    from stoic_eln.models.mixture import Mixture

    name_expr = func.coalesce(Substance.name, Mixture.name)
    sort_columns = {
        "substance": name_expr,
        "batch": InventoryItem.batch_code,
        "supplier": InventoryItem.supplier,
        "purchased": InventoryItem.purchased_at,
        "expiry": InventoryItem.expiry_date,
        "remaining": case(
            (InventoryItem.quantity_g.isnot(None), InventoryItem.quantity_g),
            else_=InventoryItem.quantity_mL,
        ),
        "total_cost": InventoryItem.total_cost_eur,
    }
    if sort not in sort_columns:
        sort = "substance"
    if direction not in ("asc", "desc"):
        direction = "asc"

    # Outer-join BOTH substance and mixture: a lot has exactly one of
    # the two FKs populated (XOR check), but the join needs to surface
    # rows for either kind so a mixture lot doesn't disappear.
    query = (
        db.session.query(InventoryItem)
        .outerjoin(Substance, InventoryItem.substance_id == Substance.id)
        .outerjoin(Mixture, InventoryItem.mixture_id == Mixture.id)
    )

    # active filter (status filters override show_inactive)
    if status == "all" and not show_inactive:
        query = query.filter(InventoryItem.is_active.is_(True))

    # text search
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                InventoryItem.batch_code.ilike(like),
                InventoryItem.supplier.ilike(like),
                InventoryItem.location.ilike(like),
                Substance.name.ilike(like),
                Substance.cas_number.ilike(like),
                Substance.molecular_formula.ilike(like),
                Mixture.name.ilike(like),
                Mixture.kind.ilike(like),
            )
        )

    # status filter (post-loaded; SQL-side filter for the obvious ones)
    today = _date.today()
    if status == "in_stock":
        query = (
            query.filter(InventoryItem.is_active.is_(True))
            .filter(
                or_(
                    InventoryItem.expiry_date.is_(None),
                    InventoryItem.expiry_date > today + timedelta(days=30),
                )
            )
            .filter(
                or_(
                    InventoryItem.quantity_g > 0,
                    InventoryItem.quantity_mL > 0,
                )
            )
        )
    elif status == "expiring":
        query = (
            query.filter(InventoryItem.is_active.is_(True))
            .filter(InventoryItem.expiry_date.isnot(None))
            .filter(InventoryItem.expiry_date >= today)
            .filter(InventoryItem.expiry_date <= today + timedelta(days=30))
        )
    elif status == "expired":
        query = query.filter(InventoryItem.expiry_date.isnot(None)).filter(
            InventoryItem.expiry_date < today
        )
    elif status == "empty":
        query = query.filter(
            or_(
                InventoryItem.quantity_g <= 0,
                InventoryItem.quantity_mL <= 0,
            )
        )
    elif status == "inactive":
        query = query.filter(InventoryItem.is_active.is_(False))

    # group filter
    if group_filter:
        from stoic_eln.models.group import Group

        query = query.join(Group, InventoryItem.group_id == Group.id).filter(
            Group.slug == group_filter
        )

    # supplier filter (exact match on dropdown)
    if supplier_filter:
        query = query.filter(InventoryItem.supplier == supplier_filter)

    # kind filter — substance / mixture / solvent / all
    if kind == "substance":
        query = query.filter(InventoryItem.substance_id.isnot(None))
    elif kind == "mixture":
        query = query.filter(InventoryItem.mixture_id.isnot(None))
    elif kind == "solvent":
        # Strict subset: only substance lots whose substance is flagged
        # as a solvent. Mixtures are excluded — they have no is_solvent
        # equivalent in their model.
        query = query.filter(InventoryItem.substance_id.isnot(None)).filter(
            Substance.is_solvent.is_(True)
        )

    # sort
    sort_col = sort_columns[sort]
    if direction == "desc":
        query = query.order_by(sort_col.desc().nulls_last(), InventoryItem.created_at.desc())
    else:
        query = query.order_by(sort_col.asc().nulls_last(), InventoryItem.created_at.desc())

    items = query.all()

    # Compute total for footer
    items_total_cost = sum((it.total_cost_eur or 0.0) for it in items)

    # Distinct suppliers for the filter dropdown
    suppliers = [
        r[0]
        for r in db.session.query(InventoryItem.supplier)
        .filter(InventoryItem.supplier.isnot(None))
        .distinct()
        .order_by(InventoryItem.supplier.asc())
        .all()
        if r[0]
    ]
    # Available groups
    from stoic_eln.models.group import Group

    groups = (
        db.session.query(Group)
        .filter(Group.is_active.is_(True))
        .order_by(Group.is_default.desc(), Group.name.asc())
        .all()
    )

    if request.headers.get("HX-Request"):
        return render_template(
            "inventory/_list_table.html",
            items=items,
            q=q,
            status=status,
            kind=kind,
            sort=sort,
            direction=direction,
            group_filter=group_filter,
            supplier_filter=supplier_filter,
            show_inactive=show_inactive,
            today=today,
            items_total_cost=items_total_cost,
        )

    return render_template(
        "inventory/list.html",
        items=items,
        q=q,
        status=status,
        kind=kind,
        sort=sort,
        direction=direction,
        group_filter=group_filter,
        supplier_filter=supplier_filter,
        show_inactive=show_inactive,
        today=today,
        suppliers=suppliers,
        groups=groups,
        items_total_cost=items_total_cost,
    )


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/substance/<int:substance_id>/new", methods=["GET", "POST"])
@login_required
@supervisor_required
def create(substance_id: int | None = None):
    """Add a new lot.

    Two entry points:

    * ``/inventory/substance/<id>/new`` (legacy URL) → lot of a pure
      substance. Still works exactly as before.
    * ``/inventory/new?substance_id=<id>`` or
      ``/inventory/new?mixture_id=<id>`` → unified entry that handles
      either kind. The lot is associated with the relevant entity
      via ``InventoryItem.substance_id`` or ``InventoryItem.mixture_id``.

    The XOR check constraint at DB level guarantees we never end up
    with both populated.
    """
    # Pull mixture_id either from path-style (none) or querystring
    raw_mixture_id = request.args.get("mixture_id")
    raw_substance_id_q = request.args.get("substance_id")

    sub = None
    mix = None
    if substance_id is not None:
        sub = db.session.get(Substance, substance_id)
    elif raw_substance_id_q:
        try:
            sub = db.session.get(Substance, int(raw_substance_id_q))
        except (TypeError, ValueError):
            sub = None
    elif raw_mixture_id:
        try:
            from stoic_eln.models.mixture import Mixture

            mix = db.session.get(Mixture, int(raw_mixture_id))
        except (TypeError, ValueError):
            mix = None

    if sub is None and mix is None:
        abort(404)

    # Compute the unit policy once. Used by the template to disable
    # fields the substance doesn't allow, and (server-side) by the
    # normalisation step below to enforce the same matrix.
    from stoic_eln.services.inventory_quantity import policy_for_substance

    unit_policy = policy_for_substance(sub)

    form = InventoryItemForm()

    # Pre-fill remaining quantity from initial when adding new
    if request.method == "GET":
        form.is_active.data = True
        # When adding a manual lot of a mixture, default the
        # expiry_date to the earliest expiry among the precursor
        # lots of the components. The user can override; we just
        # avoid forcing them to compute it by hand. Substances
        # don't have a sensible default (their expiry depends on
        # the supplier's lot), so we only do this for mixtures.
        if mix is not None and form.expiry_date.data is None:
            suggested = mix.suggested_expiry_date()
            if suggested is not None:
                form.expiry_date.data = suggested

    if form.validate_on_submit():
        # Apply the unit policy (only for substance lots — mixture
        # lots bypass the matrix).
        if sub is not None:
            from stoic_eln.services.inventory_quantity import (
                normalize_inventory_quantities,
            )

            init_g, init_mL, q_g, q_mL, err = normalize_inventory_quantities(
                initial_g=form.initial_quantity_g.data,
                initial_mL=form.initial_quantity_mL.data,
                remaining_g=form.quantity_g.data,
                remaining_mL=form.quantity_mL.data,
                substance=sub,
            )
            if err is not None:
                flash(err, "danger")
                return render_template(
                    "inventory/form.html",
                    form=form,
                    substance=sub,
                    mixture=mix,
                    unit_policy=unit_policy,
                    item=None,
                )
        else:
            q_g = form.quantity_g.data
            q_mL = form.quantity_mL.data
            init_g = form.initial_quantity_g.data
            init_mL = form.initial_quantity_mL.data

        # Pre-fill remaining from initial when one is empty (legacy
        # behaviour, retained because it's still useful for mixtures
        # and as a safety net).
        if q_g is None and init_g is not None:
            q_g = init_g
        if q_mL is None and init_mL is not None:
            q_mL = init_mL

        item = InventoryItem(
            substance_id=sub.id if sub else None,
            mixture_id=mix.id if mix else None,
            batch_code=form.batch_code.data or None,
            supplier=form.supplier.data or None,
            catalogue_number=form.catalogue_number.data or None,
            initial_quantity_g=init_g,
            initial_quantity_mL=init_mL,
            quantity_g=q_g,
            quantity_mL=q_mL,
            total_cost_eur=form.total_cost_eur.data,
            purchased_at=form.purchased_at.data,
            expiry_date=form.expiry_date.data,
            location=form.location.data or None,
            is_active=form.is_active.data,
            notes=form.notes.data or None,
            created_by_id=current_user.id,
        )
        db.session.add(item)
        db.session.commit()
        log_event(
            action="create",
            entity_type="inventory_item",
            entity_id=item.id,
            details={
                "substance_id": sub.id if sub else None,
                "mixture_id": mix.id if mix else None,
            },
        )
        if sub:
            flash(_("Lotto aggiunto a '%(name)s'.", name=sub.name), "success")
            return redirect(url_for("substances.detail", substance_id=sub.id))
        else:
            flash(_("Lotto aggiunto a '%(name)s'.", name=mix.name), "success")
            return redirect(url_for("mixtures.detail", mixture_id=mix.id))

    return render_template(
        "inventory/form.html",
        form=form,
        substance=sub,
        mixture=mix,
        unit_policy=unit_policy,
        item=None,
    )


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
@supervisor_required
def edit(item_id: int):
    item = db.session.get(InventoryItem, item_id)
    if item is None:
        abort(404)
    sub = item.substance
    mix = item.mixture

    from stoic_eln.services.inventory_quantity import policy_for_substance

    unit_policy = policy_for_substance(sub)

    form = InventoryItemForm(obj=item)
    if form.validate_on_submit():
        if sub is not None:
            from stoic_eln.services.inventory_quantity import (
                normalize_inventory_quantities,
            )

            init_g, init_mL, q_g, q_mL, err = normalize_inventory_quantities(
                initial_g=form.initial_quantity_g.data,
                initial_mL=form.initial_quantity_mL.data,
                remaining_g=form.quantity_g.data,
                remaining_mL=form.quantity_mL.data,
                substance=sub,
            )
            if err is not None:
                flash(err, "danger")
                return render_template(
                    "inventory/form.html",
                    form=form,
                    substance=sub,
                    mixture=mix,
                    unit_policy=unit_policy,
                    item=item,
                )
        else:
            q_g = form.quantity_g.data
            q_mL = form.quantity_mL.data
            init_g = form.initial_quantity_g.data
            init_mL = form.initial_quantity_mL.data

        item.batch_code = form.batch_code.data or None
        item.supplier = form.supplier.data or None
        item.catalogue_number = form.catalogue_number.data or None
        item.initial_quantity_g = init_g
        item.initial_quantity_mL = init_mL
        item.quantity_g = q_g
        item.quantity_mL = q_mL
        item.total_cost_eur = form.total_cost_eur.data
        item.purchased_at = form.purchased_at.data
        item.expiry_date = form.expiry_date.data
        item.location = form.location.data or None
        item.is_active = form.is_active.data
        item.notes = form.notes.data or None

        db.session.commit()
        log_event(
            action="update",
            entity_type="inventory_item",
            entity_id=item.id,
        )
        flash(_("Lotto aggiornato."), "success")
        if mix is not None:
            return redirect(url_for("mixtures.detail", mixture_id=mix.id))
        return redirect(url_for("substances.detail", substance_id=sub.id))

    # Attachments (Settimana 6 patch 10) — only available on existing lots
    from stoic_eln.services.attachments import list_attachments

    attachments_for_entity = list_attachments("inventory_item", item.id)

    return render_template(
        "inventory/form.html",
        form=form,
        substance=sub,
        mixture=mix,
        unit_policy=unit_policy,
        item=item,
        attachments_for_entity=attachments_for_entity,
    )


@bp.route("/<int:item_id>/deactivate", methods=["POST"])
@login_required
@supervisor_required
def deactivate(item_id: int):
    item = db.session.get(InventoryItem, item_id)
    if item is None:
        abort(404)
    item.is_active = False
    db.session.commit()
    log_event(action="deactivate", entity_type="inventory_item", entity_id=item.id)
    flash(_("Lotto disattivato."), "info")
    return redirect(url_for("substances.detail", substance_id=item.substance_id))


@bp.route("/<int:item_id>/reactivate", methods=["POST"])
@login_required
@supervisor_required
def reactivate(item_id: int):
    item = db.session.get(InventoryItem, item_id)
    if item is None:
        abort(404)
    item.is_active = True
    db.session.commit()
    log_event(action="reactivate", entity_type="inventory_item", entity_id=item.id)
    flash(_("Lotto riattivato."), "info")
    return redirect(url_for("substances.detail", substance_id=item.substance_id))


# ── Labels (Settimana 6 patch 12) ──────────────────────────────────


@bp.route("/<int:item_id>/label", methods=["GET"])
@login_required
def label_form(item_id: int):
    """Render the print-options form for a single lot's label."""
    from stoic_eln.services.labels import LABEL_FORMATS

    item = db.session.get(InventoryItem, item_id)
    if item is None:
        abort(404)
    return render_template(
        "inventory/label_print.html",
        item=item,
        formats=LABEL_FORMATS,
        default_format_key="avery_l7160",
    )


@bp.route("/<int:item_id>/label.pdf", methods=["POST"])
@login_required
def label_pdf(item_id: int):
    """Generate the label PDF for one lot and stream it inline.

    Form fields:
      * format (str, required) — one of LABEL_FORMATS keys
      * copies (int, default 1) — copies of this lot
      * start_position (int, default 0) — Avery-only: skip N slots on
        the first sheet (for re-using a partially-printed sheet)
    """
    from flask import Response
    from stoic_eln.services.labels import LABEL_FORMATS, render_labels_pdf

    item = db.session.get(InventoryItem, item_id)
    if item is None:
        abort(404)

    fmt_key = (request.form.get("format") or "").strip()
    if fmt_key not in LABEL_FORMATS:
        flash(_("Formato etichetta non valido."), "danger")
        return redirect(url_for("inventory.label_form", item_id=item_id))

    try:
        copies = max(1, min(int(request.form.get("copies") or 1), 100))
    except (TypeError, ValueError):
        copies = 1
    try:
        start_position = max(0, int(request.form.get("start_position") or 0))
    except (TypeError, ValueError):
        start_position = 0

    pdf = render_labels_pdf(
        [item],
        fmt_key,
        start_position=start_position,
        copies_per_item=copies,
    )
    log_event(
        action="print_label",
        entity_type="inventory_item",
        entity_id=item.id,
        details={"format": fmt_key, "copies": copies},
    )

    safe_batch = (item.batch_code or f"lot-{item.id}").replace("/", "-")
    filename = f"etichetta_{safe_batch}_{fmt_key}.pdf"
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Length": str(len(pdf)),
        },
    )


@bp.route("/<int:item_id>/report.pdf", methods=["GET"])
@login_required
def report_pdf(item_id: int):
    """Generate the traceability report PDF for a single lot.

    Single-shot endpoint (no options form needed): always renders the
    full content — identity, quantity, origin, consumptions, safety,
    notes, attachments. ~1-2 pages depending on how much history the
    lot has.

    Streamed inline so the browser shows it in a tab; users can then
    save or print from there.
    """
    from flask import Response
    from stoic_eln.services.pdf_lot import render_lot_report

    item = db.session.get(InventoryItem, item_id)
    if item is None:
        abort(404)

    pdf = render_lot_report(item)
    log_event(
        action="print_report",
        entity_type="inventory_item",
        entity_id=item.id,
        details={"kind": "lot_report"},
    )

    safe_batch = (item.batch_code or f"lot-{item.id}").replace("/", "-")
    filename = f"scheda_lotto_{safe_batch}.pdf"
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Length": str(len(pdf)),
        },
    )
