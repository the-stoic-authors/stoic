"""Stoic ELN — Inventory routes."""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import or_

from stoic_eln.blueprints.inventory import bp
from stoic_eln.blueprints.inventory.forms import InventoryItemForm
from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.substance import Substance
from stoic_eln.services.audit import log_event


@bp.route("/")
@login_required
def list_view():
    """Warehouse view: all lots with filters."""
    q = request.args.get("q", "").strip()
    show_inactive = request.args.get("show_inactive") == "1"

    query = (
        db.session.query(InventoryItem)
        .join(Substance, InventoryItem.substance_id == Substance.id)
    )
    if not show_inactive:
        query = query.filter(InventoryItem.is_active.is_(True))

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
            )
        )

    query = query.order_by(Substance.name.asc(), InventoryItem.created_at.desc())
    items = query.all()

    if request.headers.get("HX-Request"):
        return render_template(
            "inventory/_list_table.html",
            items=items,
            q=q,
        )

    return render_template(
        "inventory/list.html",
        items=items,
        q=q,
        show_inactive=show_inactive,
    )


@bp.route("/substance/<int:substance_id>/new", methods=["GET", "POST"])
@login_required
def create(substance_id: int):
    """Add a new lot to a specific substance."""
    sub = db.session.get(Substance, substance_id)
    if sub is None:
        abort(404)

    form = InventoryItemForm()

    # Pre-fill remaining quantity from initial when adding new
    if request.method == "GET":
        form.is_active.data = True

    if form.validate_on_submit():
        # If quantity_residua is empty, use initial
        q_g = form.quantity_g.data
        q_mL = form.quantity_mL.data
        init_g = form.initial_quantity_g.data
        init_mL = form.initial_quantity_mL.data
        if q_g is None and init_g is not None:
            q_g = init_g
        if q_mL is None and init_mL is not None:
            q_mL = init_mL

        item = InventoryItem(
            substance_id=sub.id,
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
            details={"substance_id": sub.id},
        )
        flash(_("Lotto aggiunto a '%(name)s'.", name=sub.name), "success")
        return redirect(url_for("substances.detail", substance_id=sub.id))

    return render_template(
        "inventory/form.html", form=form, substance=sub, item=None
    )


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit(item_id: int):
    item = db.session.get(InventoryItem, item_id)
    if item is None:
        abort(404)
    sub = item.substance

    form = InventoryItemForm(obj=item)
    if form.validate_on_submit():
        item.batch_code = form.batch_code.data or None
        item.supplier = form.supplier.data or None
        item.catalogue_number = form.catalogue_number.data or None
        item.initial_quantity_g = form.initial_quantity_g.data
        item.initial_quantity_mL = form.initial_quantity_mL.data
        item.quantity_g = form.quantity_g.data
        item.quantity_mL = form.quantity_mL.data
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
        return redirect(url_for("substances.detail", substance_id=sub.id))

    return render_template(
        "inventory/form.html", form=form, substance=sub, item=item
    )


@bp.route("/<int:item_id>/deactivate", methods=["POST"])
@login_required
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
def reactivate(item_id: int):
    item = db.session.get(InventoryItem, item_id)
    if item is None:
        abort(404)
    item.is_active = True
    db.session.commit()
    log_event(action="reactivate", entity_type="inventory_item", entity_id=item.id)
    flash(_("Lotto riattivato."), "info")
    return redirect(url_for("substances.detail", substance_id=item.substance_id))
