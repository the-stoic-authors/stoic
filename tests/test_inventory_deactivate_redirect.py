"""Regression: deactivating/reactivating a *mixture* lot from inventory.

The trash icon posts to /inventory/<id>/deactivate, which used to redirect
unconditionally to ``substances.detail`` with the lot's ``substance_id`` — None
for a mixture lot → BuildError (500). It now redirects to the owner's detail
page (mixture or substance).
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models import Group, InventoryItem, Mixture, Substance, User
from stoic_eln.models.mixture import MIXTURE_KIND_SOLUTION


def _setup():
    u = User(
        username="sup",
        full_name="Sup",
        operator_code="SU",
        role="admin",
        is_admin=True,
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
    return dict(uid=u.id, sub_id=sub.id, mix_id=mix.id, sub_lot=sub_lot.id, mix_lot=mix_lot.id)


def _login(client, uid):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True


def test_deactivate_mixture_lot_redirects_to_mixture(app, client):
    with app.app_context():
        ctx = _setup()
    _login(client, ctx["uid"])
    resp = client.post(f"/inventory/{ctx['mix_lot']}/deactivate")
    assert resp.status_code == 302
    assert f"/mixtures/{ctx['mix_id']}" in resp.headers["Location"]
    with app.app_context():
        assert db.session.get(InventoryItem, ctx["mix_lot"]).is_active is False


def test_reactivate_mixture_lot_redirects_to_mixture(app, client):
    with app.app_context():
        ctx = _setup()
    _login(client, ctx["uid"])
    resp = client.post(f"/inventory/{ctx['mix_lot']}/reactivate")
    assert resp.status_code == 302
    assert f"/mixtures/{ctx['mix_id']}" in resp.headers["Location"]


def test_deactivate_substance_lot_still_redirects_to_substance(app, client):
    with app.app_context():
        ctx = _setup()
    _login(client, ctx["uid"])
    resp = client.post(f"/inventory/{ctx['sub_lot']}/deactivate")
    assert resp.status_code == 302
    assert f"/substances/{ctx['sub_id']}" in resp.headers["Location"]
