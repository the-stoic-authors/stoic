"""Suppliers — contact book for reagent/chemical suppliers."""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import login_required

from stoic_eln.blueprints.suppliers import bp
from stoic_eln.extensions import db
from stoic_eln.models.order import Order
from stoic_eln.models.supplier import Supplier
from stoic_eln.services.audit import log_event


@bp.route("/")
@login_required
def list_view():
    q = (request.args.get("q") or "").strip()
    query = db.session.query(Supplier).order_by(Supplier.name)
    if q:
        query = query.filter(Supplier.name.ilike(f"%{q}%"))
    suppliers = query.all()
    return render_template("suppliers/list.html", suppliers=suppliers, q=q)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash(_("Il nome del fornitore è obbligatorio."), "warning")
            return render_template("suppliers/form.html", supplier=None)

        if db.session.query(Supplier).filter_by(name=name).first():
            flash(_("Esiste già un fornitore con questo nome."), "warning")
            return render_template("suppliers/form.html", supplier=None)

        s = Supplier(
            name=name,
            address=(request.form.get("address") or "").strip() or None,
            phone=(request.form.get("phone") or "").strip() or None,
            email=(request.form.get("email") or "").strip() or None,
            url=(request.form.get("url") or "").strip() or None,
            portal_username=(request.form.get("portal_username") or "").strip() or None,
            portal_password=(request.form.get("portal_password") or "").strip() or None,
            notes=(request.form.get("notes") or "").strip() or None,
        )
        db.session.add(s)
        db.session.commit()
        log_event(action="create", entity_type="supplier", entity_id=s.id, details={"name": s.name})
        flash(_("Fornitore %(name)s aggiunto.", name=s.name), "success")
        return redirect(url_for("suppliers.detail", supplier_id=s.id))

    return render_template("suppliers/form.html", supplier=None)


@bp.route("/<int:supplier_id>")
@login_required
def detail(supplier_id: int):
    s = db.session.get(Supplier, supplier_id)
    if s is None:
        abort(404)
    orders = (
        db.session.query(Order)
        .filter_by(supplier_id=supplier_id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return render_template("suppliers/detail.html", supplier=s, orders=orders)


@bp.route("/<int:supplier_id>/edit", methods=["GET", "POST"])
@login_required
def edit(supplier_id: int):
    s = db.session.get(Supplier, supplier_id)
    if s is None:
        abort(404)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash(_("Il nome del fornitore è obbligatorio."), "warning")
            return render_template("suppliers/form.html", supplier=s)

        existing = db.session.query(Supplier).filter_by(name=name).first()
        if existing and existing.id != s.id:
            flash(_("Esiste già un fornitore con questo nome."), "warning")
            return render_template("suppliers/form.html", supplier=s)

        s.name = name
        s.address = (request.form.get("address") or "").strip() or None
        s.phone = (request.form.get("phone") or "").strip() or None
        s.email = (request.form.get("email") or "").strip() or None
        s.url = (request.form.get("url") or "").strip() or None
        s.portal_username = (request.form.get("portal_username") or "").strip() or None
        s.portal_password = (request.form.get("portal_password") or "").strip() or None
        s.notes = (request.form.get("notes") or "").strip() or None
        db.session.commit()
        log_event(action="update", entity_type="supplier", entity_id=s.id, details={"name": s.name})
        flash(_("Fornitore aggiornato."), "success")
        return redirect(url_for("suppliers.detail", supplier_id=s.id))

    return render_template("suppliers/form.html", supplier=s)


@bp.route("/<int:supplier_id>/delete", methods=["POST"])
@login_required
def delete(supplier_id: int):
    s = db.session.get(Supplier, supplier_id)
    if s is None:
        abort(404)
    # Detach orders (set supplier_id to NULL, keep supplier name string)
    for order in db.session.query(Order).filter_by(supplier_id=supplier_id).all():
        order.supplier_id = None
    db.session.delete(s)
    db.session.commit()
    log_event(
        action="delete", entity_type="supplier", entity_id=supplier_id, details={"name": s.name}
    )
    flash(_("Fornitore eliminato."), "success")
    return redirect(url_for("suppliers.list_view"))
