"""Tests for Order model and routes when the target is a Mixture.

These tests mirror the existing test_order_* tests in test_run_setup.py
but exercise the Mixture path: create a planned order, mark it as
ordered, receive it (which creates an InventoryItem with mixture_id
set, not substance_id), and cancel. Also exercises the XOR validation
on the route (POST without target, POST with both targets).
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    InventoryItem,
    Mixture,
    Order,
    Substance,
    User,
)
from stoic_eln.models.mixture import MIXTURE_KIND_SOLUTION


# ── Helpers ────────────────────────────────────────────────────────


def _setup_user_and_mixture(name: str = "HCl 12N") -> tuple[int, int]:
    """Create an admin user + a mixture, return (user_id, mixture_id)."""
    u = User(
        username="r",
        full_name="R",
        operator_code="RR",
        role="admin",
        is_admin=True,
        is_active=True,
        locale="it",
    )
    u.set_password("x")
    db.session.add(u)

    m = Mixture(
        name=name,
        kind=MIXTURE_KIND_SOLUTION,
        primary_concentration=12.0,
        primary_concentration_unit="N",
    )
    db.session.add(m)
    db.session.commit()
    return u.id, m.id


def _login(client):
    client.post("/auth/login", data={"username": "r", "password": "x", "submit": "x"})


# ── Model-level XOR ─────────────────────────────────────────────────


def test_order_xor_rejects_both(app):
    """An Order with both substance_id AND mixture_id violates XOR."""
    with app.app_context():
        u = User(
            username="r",
            full_name="R",
            operator_code="RR",
            role="admin",
            is_admin=True,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        s = Substance(name="HCl", molecular_weight=36.46)
        db.session.add(s)
        m = Mixture(name="HCl 12N", kind=MIXTURE_KIND_SOLUTION)
        db.session.add(m)
        g = Group(name="L", slug="l")
        db.session.add(g)
        db.session.commit()

        bad = Order(
            substance_id=s.id,
            mixture_id=m.id,  # XOR violation
            group_id=g.id,
            ordered_quantity_mL=500.0,
        )
        db.session.add(bad)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_order_xor_rejects_neither(app):
    """An Order with neither substance_id nor mixture_id violates XOR."""
    with app.app_context():
        u = User(
            username="r",
            full_name="R",
            operator_code="RR",
            role="admin",
            is_admin=True,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        g = Group(name="L", slug="l")
        db.session.add(g)
        db.session.commit()

        bad = Order(
            substance_id=None,
            mixture_id=None,  # XOR violation
            group_id=g.id,
            ordered_quantity_mL=500.0,
        )
        db.session.add(bad)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_order_kind_property(app):
    """``order.kind`` reflects substance vs mixture targeting.

    Also verifies that ``target_name`` returns the mixture's
    ``display_label`` (with concentration) rather than just the name,
    so two mixtures named "HCl" with different concentrations are
    distinguishable in lists and dropdowns.
    """
    with app.app_context():
        u = User(
            username="r",
            full_name="R",
            operator_code="RR",
            role="admin",
            is_admin=True,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        s = Substance(name="HCl", molecular_weight=36.46)
        m12 = Mixture(
            name="HCl",
            kind=MIXTURE_KIND_SOLUTION,
            primary_concentration=12.0,
            primary_concentration_unit="N",
        )
        m6 = Mixture(
            name="HCl",
            kind=MIXTURE_KIND_SOLUTION,
            primary_concentration=6.0,
            primary_concentration_unit="N",
        )
        db.session.add_all([s, m12, m6])
        g = Group(name="L", slug="l")
        db.session.add(g)
        db.session.commit()

        o_sub = Order(substance_id=s.id, group_id=g.id, ordered_quantity_g=10.0)
        o_mix_12 = Order(mixture_id=m12.id, group_id=g.id, ordered_quantity_mL=500.0)
        o_mix_6 = Order(mixture_id=m6.id, group_id=g.id, ordered_quantity_mL=500.0)
        db.session.add_all([o_sub, o_mix_12, o_mix_6])
        db.session.commit()

        assert o_sub.kind == "substance"
        assert o_sub.target_name == "HCl"
        assert o_mix_12.kind == "mixture"
        # display_label includes the concentration to disambiguate
        assert "12" in o_mix_12.target_name
        assert "N" in o_mix_12.target_name
        assert "6" in o_mix_6.target_name
        # The two mixture orders are distinguishable from each other
        assert o_mix_12.target_name != o_mix_6.target_name


# ── Route-level: plan, mark, receive, cancel ────────────────────────


def test_order_mixture_plan(app, client):
    """Creating an order from /orders/new?mixture_id=N puts it in planned."""
    with app.app_context():
        _, mid = _setup_user_and_mixture("HCl 12N")

    _login(client)

    r = client.post(
        "/orders/new",
        data={
            "csrf_token": "",
            "mixture_id": str(mid),
            "supplier": "Sigma-Aldrich",
            "catalogue_number": "320331-1L",
            "ordered_quantity_mL": "1000",
            "ordered_total_eur": "42.50",
        },
    )
    assert r.status_code == 302

    with app.app_context():
        o = db.session.query(Order).first()
        assert o is not None
        assert o.kind == "mixture"
        assert o.mixture_id == mid
        assert o.substance_id is None
        assert o.status == "planned"
        assert o.supplier == "Sigma-Aldrich"
        assert o.catalogue_number == "320331-1L"
        assert o.ordered_quantity_mL == 1000.0
        assert o.ordered_total_eur == 42.50


def test_order_mixture_full_lifecycle(app, client):
    """planned → ordered → received: creates InventoryItem with mixture_id."""
    with app.app_context():
        _, mid = _setup_user_and_mixture("HCl 12N")

    _login(client)

    # 1. Plan
    client.post(
        "/orders/new",
        data={
            "csrf_token": "",
            "mixture_id": str(mid),
            "ordered_quantity_mL": "500",
        },
    )
    with app.app_context():
        oid = db.session.query(Order).first().id

    # 2. Mark as ordered
    client.post(
        f"/orders/{oid}/mark_ordered",
        data={
            "csrf_token": "",
            "ordered_at": date.today().isoformat(),
        },
    )
    with app.app_context():
        assert db.session.get(Order, oid).status == "ordered"

    # 3. Receive
    client.post(
        f"/orders/{oid}/receive",
        data={
            "csrf_token": "",
            "received_quantity_mL": "500",
            "received_at": date.today().isoformat(),
            "batch_code": "STB-12345",
            "expiry_date": "2027-12-31",
        },
    )
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.status == "received"
        assert o.inventory_item_id is not None
        lot = db.session.get(InventoryItem, o.inventory_item_id)
        # The crucial assertion: lot is a Mixture lot, not a Substance lot
        assert lot.mixture_id == mid
        assert lot.substance_id is None
        assert lot.batch_code == "STB-12345"
        assert lot.quantity_mL == 500.0
        assert lot.expiry_date == date(2027, 12, 31)


def test_order_mixture_partial(app, client):
    """Receiving less than ordered → status='received_partial'."""
    with app.app_context():
        _, mid = _setup_user_and_mixture()

    _login(client)
    client.post(
        "/orders/new",
        data={
            "csrf_token": "",
            "mixture_id": str(mid),
            "ordered_quantity_mL": "1000",
        },
    )
    with app.app_context():
        oid = db.session.query(Order).first().id

    # Receive only 800mL
    client.post(
        f"/orders/{oid}/receive",
        data={
            "csrf_token": "",
            "received_quantity_mL": "800",
            "partial_reason": "Bottiglia da 1L non disponibile, spedita da 800 mL",
        },
    )
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.status == "received_partial"
        assert o.inventory_item.quantity_mL == 800.0
        assert o.inventory_item.mixture_id == mid


def test_order_mixture_cancel(app, client):
    """A planned mixture order can be cancelled."""
    with app.app_context():
        _, mid = _setup_user_and_mixture()

    _login(client)
    client.post(
        "/orders/new",
        data={
            "csrf_token": "",
            "mixture_id": str(mid),
            "ordered_quantity_mL": "500",
        },
    )
    with app.app_context():
        oid = db.session.query(Order).first().id

    client.post(
        f"/orders/{oid}/cancel",
        data={"csrf_token": "", "reason": "Cambiati i piani"},
    )
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.status == "cancelled"
        assert "Cambiati i piani" in (o.notes or "")


# ── Route-level: validation ─────────────────────────────────────────


def test_order_new_rejects_both_targets(app, client):
    """POST /orders/new with both substance_id and mixture_id → error flash."""
    with app.app_context():
        _, mid = _setup_user_and_mixture()
        s = Substance(name="HCl", molecular_weight=36.46)
        db.session.add(s)
        db.session.commit()
        sid = s.id

    _login(client)
    r = client.post(
        "/orders/new",
        data={
            "csrf_token": "",
            "substance_id": str(sid),
            "mixture_id": str(mid),  # both set — should fail
            "ordered_quantity_mL": "500",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302  # redirect back to form, no order created

    with app.app_context():
        assert db.session.query(Order).count() == 0


def test_order_new_rejects_neither_target(app, client):
    """POST /orders/new without any target → error flash."""
    with app.app_context():
        _setup_user_and_mixture()

    _login(client)
    r = client.post(
        "/orders/new",
        data={
            "csrf_token": "",
            "ordered_quantity_mL": "500",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302  # redirect back, no order

    with app.app_context():
        assert db.session.query(Order).count() == 0


# ── List view shows both kinds ──────────────────────────────────────


def test_order_list_shows_both_kinds(app, client):
    """The /orders/ page lists both substance and mixture orders together."""
    with app.app_context():
        _, mid = _setup_user_and_mixture()
        s = Substance(name="EtOAc", molecular_weight=88.11)
        db.session.add(s)
        db.session.commit()
        sid = s.id

    _login(client)

    # Plan one of each kind
    client.post(
        "/orders/new",
        data={"csrf_token": "", "substance_id": str(sid), "ordered_quantity_mL": "1000"},
    )
    client.post(
        "/orders/new",
        data={"csrf_token": "", "mixture_id": str(mid), "ordered_quantity_mL": "500"},
    )

    r = client.get("/orders/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Both target names should appear
    assert "EtOAc" in body
    assert "HCl 12N" in body
    # And the "miscela" badge for the mixture one
    assert "miscela" in body.lower()
