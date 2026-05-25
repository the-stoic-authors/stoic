"""Stoic ELN — Orders routes (Settimana 6 patch 3).

Routes:
  GET  /orders/                          → list with filters
  GET  /orders/new                       → empty form
  GET  /orders/new?substance_id=…        → form pre-populated for a substance
  POST /orders/new                       → create planned order
  GET  /orders/<id>                      → detail page
  GET  /orders/<id>/edit                 → edit form (only while open)
  POST /orders/<id>/edit                 → save edits
  POST /orders/<id>/mark_ordered         → planned → ordered (form-driven)
  GET  /orders/<id>/receive              → receive form
  POST /orders/<id>/receive              → close + create lot
  POST /orders/<id>/cancel               → cancel
"""

from __future__ import annotations

from datetime import date, datetime

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
from sqlalchemy import or_, func

from stoic_eln.blueprints.orders import bp
from stoic_eln.extensions import db
from stoic_eln.models.group import Group
from stoic_eln.models.inventory import InventoryItem  # noqa: F401  (relationship)
from stoic_eln.models.order import (
    ALL_STATUSES,
    OPEN_STATUSES,
    Order,
)
from stoic_eln.models.substance import Substance
from stoic_eln.services import order_service
from stoic_eln.services.audit import log_event
from stoic_eln.services.group_service import current_user_group


def _parse_float(name: str) -> float | None:
    raw = request.form.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_date(name: str) -> date | None:
    raw = request.form.get(name, "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


# ── List ────────────────────────────────────────────────────────────────


@bp.route("/")
@login_required
def list_view():
    """All orders — defaults to 'open' (planned + ordered)."""
    status = (request.args.get("status") or "open").lower()
    supplier_filter = request.args.get("supplier", "").strip()
    group_filter = request.args.get("group", "").strip()
    q = request.args.get("q", "").strip()

    query = db.session.query(Order).join(Substance, Order.substance_id == Substance.id)

    if status == "open":
        query = query.filter(Order.status.in_(OPEN_STATUSES))
    elif status in ALL_STATUSES:
        query = query.filter(Order.status == status)
    # status == "all" → no filter

    if supplier_filter:
        query = query.filter(Order.supplier == supplier_filter)
    if group_filter:
        query = query.join(Group, Order.group_id == Group.id).filter(Group.slug == group_filter)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Substance.name.ilike(like),
                Substance.cas_number.ilike(like),
                Order.supplier.ilike(like),
                Order.catalogue_number.ilike(like),
                Order.internal_order_ref.ilike(like),
            )
        )

    # Sort: open orders first by expected delivery, closed by ordered_at desc
    orders = query.order_by(
        Order.status.asc(),
        Order.expected_delivery_date.asc().nulls_last(),
        Order.created_at.desc(),
    ).all()

    # Totals for the footer
    total_open_eur = sum((o.ordered_total_eur or 0.0) for o in orders if o.is_open)

    suppliers = [
        r[0]
        for r in db.session.query(Order.supplier)
        .filter(Order.supplier.isnot(None))
        .distinct()
        .order_by(Order.supplier.asc())
        .all()
        if r[0]
    ]
    groups = (
        db.session.query(Group)
        .filter(Group.is_active.is_(True))
        .order_by(Group.is_default.desc(), Group.name.asc())
        .all()
    )

    return render_template(
        "orders/list.html",
        orders=orders,
        status=status,
        supplier_filter=supplier_filter,
        group_filter=group_filter,
        q=q,
        suppliers=suppliers,
        groups=groups,
        today=date.today(),
        total_open_eur=total_open_eur,
    )


# ── New ─────────────────────────────────────────────────────────────────


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    """Create a planned order. Pre-populates substance if ?substance_id=N."""
    pre_substance_id = request.args.get("substance_id", type=int)

    if request.method == "POST":
        substance_id = request.form.get("substance_id", type=int)
        sub = db.session.get(Substance, substance_id) if substance_id else None
        if sub is None:
            flash(_("Sostanza non trovata."), "danger")
            return redirect(url_for("orders.new"))

        # Quantity: at least one of g/mL must be > 0
        qty_g = _parse_float("ordered_quantity_g")
        qty_mL = _parse_float("ordered_quantity_mL")
        if not (qty_g and qty_g > 0) and not (qty_mL and qty_mL > 0):
            flash(_("Inserisci una quantità (g o mL)."), "danger")
            return redirect(url_for("orders.new", substance_id=sub.id))

        group = current_user_group(current_user)

        order = Order(
            substance_id=sub.id,
            group_id=group.id,
            supplier=(request.form.get("supplier") or "").strip() or None,
            catalogue_number=(request.form.get("catalogue_number") or "").strip() or None,
            ordered_quantity_g=qty_g,
            ordered_quantity_mL=qty_mL,
            ordered_total_eur=_parse_float("ordered_total_eur"),
            expected_delivery_date=_parse_date("expected_delivery_date"),
            internal_order_ref=(request.form.get("internal_order_ref") or "").strip() or None,
            notes=(request.form.get("notes") or "").strip() or None,
            created_by_id=current_user.id,
        )
        db.session.add(order)
        db.session.commit()

        log_event(
            action="create_order",
            entity_type="order",
            entity_id=order.id,
            details={"substance_id": sub.id, "qty_g": qty_g, "qty_mL": qty_mL},
        )
        flash(_("Ordine pianificato per %(name)s.", name=sub.name), "success")
        return redirect(url_for("orders.detail", order_id=order.id))

    # GET: render form. Pre-population from query string allows the
    # shopping list page to send a substance with a suggested
    # quantity/supplier/cost already filled in — the user can still
    # edit anything before submitting.
    pre_substance = db.session.get(Substance, pre_substance_id) if pre_substance_id else None

    pre = {}
    if pre_substance is not None:
        # Only pre-fill if a substance was given (otherwise we'd put
        # values in a form with no substance, which would be confusing).
        def _q_float(name):
            raw = (request.args.get(name) or "").strip()
            if not raw:
                return None
            try:
                return float(raw.replace(",", "."))
            except ValueError:
                return None

        pre = {
            "ordered_quantity_g": _q_float("ordered_quantity_g"),
            "ordered_quantity_mL": _q_float("ordered_quantity_mL"),
            "ordered_total_eur": _q_float("ordered_total_eur"),
            "supplier": (request.args.get("supplier") or "").strip() or None,
            "catalogue_number": (request.args.get("catalogue_number") or "").strip() or None,
        }

    substances = (
        db.session.query(Substance)
        .filter(Substance.is_active.is_(True))
        .order_by(func.lower(Substance.name).asc())
        .all()
    )
    return render_template(
        "orders/form.html",
        order=None,
        pre_substance=pre_substance,
        pre=pre,
        substances=substances,
    )


# ── Detail ──────────────────────────────────────────────────────────────


@bp.route("/<int:order_id>")
@login_required
def detail(order_id: int):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    return render_template(
        "orders/detail.html",
        order=order,
        today=date.today(),
    )


# ── Edit ────────────────────────────────────────────────────────────────


@bp.route("/<int:order_id>/edit", methods=["GET", "POST"])
@login_required
def edit(order_id: int):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    if not order.is_open:
        flash(_("Ordine non più modificabile (stato: %(s)s).", s=order.status), "warning")
        return redirect(url_for("orders.detail", order_id=order.id))

    if request.method == "POST":
        order.supplier = (request.form.get("supplier") or "").strip() or None
        order.catalogue_number = (request.form.get("catalogue_number") or "").strip() or None
        order.ordered_quantity_g = _parse_float("ordered_quantity_g")
        order.ordered_quantity_mL = _parse_float("ordered_quantity_mL")
        order.ordered_total_eur = _parse_float("ordered_total_eur")
        order.expected_delivery_date = _parse_date("expected_delivery_date")
        order.internal_order_ref = (request.form.get("internal_order_ref") or "").strip() or None
        order.notes = (request.form.get("notes") or "").strip() or None
        db.session.commit()
        log_event(action="update_order", entity_type="order", entity_id=order.id)
        flash(_("Ordine aggiornato."), "success")
        return redirect(url_for("orders.detail", order_id=order.id))

    substances = (
        db.session.query(Substance)
        .filter(Substance.is_active.is_(True))
        .order_by(func.lower(Substance.name).asc())
        .all()
    )
    return render_template(
        "orders/form.html",
        order=order,
        pre_substance=order.substance,
        pre={},
        substances=substances,
    )


# ── Mark as ordered ─────────────────────────────────────────────────────


@bp.route("/<int:order_id>/mark_ordered", methods=["POST"])
@login_required
def mark_ordered(order_id: int):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    try:
        order_service.mark_as_ordered(
            order,
            ordered_at=_parse_date("ordered_at"),
            expected_delivery_date=_parse_date("expected_delivery_date"),
            internal_order_ref=((request.form.get("internal_order_ref") or "").strip() or None),
            actor=current_user,
        )
    except order_service.OrderError as e:
        flash(str(e), "danger")
        return redirect(url_for("orders.detail", order_id=order.id))
    db.session.commit()
    log_event(action="mark_order_ordered", entity_type="order", entity_id=order.id)
    flash(_("Ordine segnato come ordinato."), "success")
    return redirect(url_for("orders.detail", order_id=order.id))


# ── Receive ─────────────────────────────────────────────────────────────


@bp.route("/<int:order_id>/receive", methods=["GET", "POST"])
@login_required
def receive(order_id: int):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    if not order.is_open:
        flash(_("Ordine già finalizzato."), "warning")
        return redirect(url_for("orders.detail", order_id=order.id))

    if request.method == "POST":
        # Determine if this is partial: actual differs from ordered
        actual_g = _parse_float("received_quantity_g")
        actual_mL = _parse_float("received_quantity_mL")

        is_partial = False
        if order.ordered_quantity_g and actual_g is not None:
            if actual_g < order.ordered_quantity_g:
                is_partial = True
        if order.ordered_quantity_mL and actual_mL is not None:
            if actual_mL < order.ordered_quantity_mL:
                is_partial = True
        # User can also force partial via checkbox
        if request.form.get("is_partial") == "1":
            is_partial = True

        notes_extra = (request.form.get("partial_reason") or "").strip() or None

        try:
            lot = order_service.receive_order(
                order,
                received_at=_parse_date("received_at") or date.today(),
                actual_quantity_g=actual_g,
                actual_quantity_mL=actual_mL,
                actual_total_eur=_parse_float("received_total_eur"),
                batch_code=(request.form.get("batch_code") or "").strip() or None,
                expiry_date=_parse_date("expiry_date"),
                location=(request.form.get("location") or "").strip() or None,
                notes_extra=notes_extra,
                is_partial=is_partial,
                actor=current_user,
            )
        except order_service.OrderError as e:
            flash(str(e), "danger")
            return redirect(url_for("orders.receive", order_id=order.id))

        db.session.commit()
        log_event(
            action="receive_order",
            entity_type="order",
            entity_id=order.id,
            details={"lot_id": lot.id, "partial": is_partial},
        )

        if is_partial:
            flash(_("Ordine ricevuto parzialmente. Lotto creato."), "success")
        else:
            flash(_("Ordine ricevuto. Lotto creato."), "success")
        return redirect(url_for("orders.detail", order_id=order.id))

    return render_template(
        "orders/receive.html",
        order=order,
        today=date.today(),
    )


# ── Cancel ──────────────────────────────────────────────────────────────


@bp.route("/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel(order_id: int):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    reason = (request.form.get("reason") or "").strip() or None
    try:
        order_service.cancel_order(order, reason=reason, actor=current_user)
    except order_service.OrderError as e:
        flash(str(e), "danger")
        return redirect(url_for("orders.detail", order_id=order.id))
    db.session.commit()
    log_event(
        action="cancel_order", entity_type="order", entity_id=order.id, details={"reason": reason}
    )
    flash(_("Ordine annullato."), "success")
    return redirect(url_for("orders.detail", order_id=order.id))


# ── Shopping list (Settimana 6 patch 4) ────────────────────────────────


@bp.route("/shopping_list/")
@login_required
def shopping_list():
    """Suggested re-orders based on inventory state."""
    from stoic_eln.services.shopping_list import build_shopping_list, get_flags

    suggestions = build_shopping_list()
    flags = get_flags()
    return render_template(
        "orders/shopping_list.html",
        suggestions=suggestions,
        flags=flags,
        today=date.today(),
    )


@bp.route("/shopping_list/create_orders", methods=["POST"])
@login_required
def shopping_list_create_orders():
    """Create planned orders for the substances ticked in the shopping list."""
    from stoic_eln.services.shopping_list import build_shopping_list

    selected_ids = set(request.form.getlist("substance_id", type=int))
    if not selected_ids:
        flash(_("Nessuna sostanza selezionata."), "warning")
        return redirect(url_for("orders.shopping_list"))

    suggestions = build_shopping_list()
    by_id = {s.substance.id: s for s in suggestions}

    group = current_user_group(current_user)

    n_created = 0
    for sub_id in selected_ids:
        sug = by_id.get(sub_id)
        if sug is None:
            continue
        if sug.has_open_order:
            # Skip — there's already an open order for this substance.
            continue
        # Only create if we have at least a quantity. Otherwise the form
        # should have given the user a chance to fill it; we ignore here.
        if sug.suggested_quantity_g is None and sug.suggested_quantity_mL is None:
            continue
        order = Order(
            substance_id=sub_id,
            group_id=group.id,
            supplier=sug.last_supplier,
            catalogue_number=sug.last_catalogue_number,
            ordered_quantity_g=sug.suggested_quantity_g,
            ordered_quantity_mL=sug.suggested_quantity_mL,
            ordered_total_eur=sug.estimated_total_cost_eur,
            notes=_(
                "Generato dalla lista della spesa (motivo: %(r)s).",
                r=sug.reason_label_color[0],
            ),
            created_by_id=current_user.id,
        )
        db.session.add(order)
        n_created += 1
    db.session.commit()
    log_event(
        action="bulk_create_orders_from_shopping_list",
        entity_type="order",
        details={"n": n_created},
    )

    if n_created:
        flash(_("Creati %(n)d ordini pianificati.", n=n_created), "success")
    else:
        flash(_("Nessun ordine creato (potrebbero essere già aperti)."), "warning")
    return redirect(url_for("orders.list_view", status="planned"))


@bp.route("/shopping_list/settings", methods=["POST"])
@login_required
def shopping_list_settings():
    """Update which categories appear in the shopping list."""
    from stoic_eln.services.shopping_list import set_flags

    set_flags(
        include_low_stock=request.form.get("include_low_stock") == "1",
        include_empty=request.form.get("include_empty") == "1",
        include_expiring=request.form.get("include_expiring") == "1",
    )
    log_event(action="update_shopping_list_settings", entity_type="setting")
    flash(_("Preferenze lista della spesa aggiornate."), "success")
    return redirect(url_for("orders.shopping_list"))
