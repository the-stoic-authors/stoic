"""Regression: the print-label page for a *mixture* lot.

`/inventory/<id>/label` rendered a breadcrumb + subtitle that dereferenced
`item.substance` unconditionally → crash for a mixture lot (no substance).
It now branches on the lot's owner (mixture or substance).
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models import Group, InventoryItem, Mixture, Substance, User
from stoic_eln.models.mixture import MIXTURE_KIND_SOLUTION


def _setup():
    u = User(
        username="op",
        full_name="Op",
        operator_code="OP",
        role="operator",
        is_admin=False,
        is_active=True,
        locale="it",
    )
    u.set_password("x")
    g = Group(name="L", slug="l", is_default=True, is_active=True)
    sub = Substance(name="CuBr2", molecular_weight=223.35)
    mix = Mixture(
        name="HCl 6N",
        kind=MIXTURE_KIND_SOLUTION,
        primary_concentration=6.0,
        primary_concentration_unit="N",
    )
    db.session.add_all([u, g, sub, mix])
    db.session.flush()
    sub_lot = InventoryItem(
        substance_id=sub.id,
        group_id=g.id,
        batch_code="S-1",
        quantity_g=100.0,
        initial_quantity_g=100.0,
        is_active=True,
    )
    mix_lot = InventoryItem(
        mixture_id=mix.id,
        group_id=g.id,
        batch_code="M-1",
        quantity_mL=500.0,
        initial_quantity_mL=500.0,
        is_active=True,
    )
    db.session.add_all([sub_lot, mix_lot])
    db.session.commit()
    return dict(uid=u.id, sub_lot=sub_lot.id, mix_lot=mix_lot.id)


def _login(client, uid):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True


def test_label_page_renders_for_mixture_lot(app, client):
    with app.app_context():
        ctx = _setup()
    _login(client, ctx["uid"])
    resp = client.get(f"/inventory/{ctx['mix_lot']}/label")
    assert resp.status_code == 200
    assert b"HCl 6N" in resp.data


def test_label_page_still_renders_for_substance_lot(app, client):
    with app.app_context():
        ctx = _setup()
    _login(client, ctx["uid"])
    resp = client.get(f"/inventory/{ctx['sub_lot']}/label")
    assert resp.status_code == 200
    assert b"CuBr2" in resp.data
