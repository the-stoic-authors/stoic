"""Integration tests for the suppliers blueprint."""

from __future__ import annotations

import re

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.order import Order
from stoic_eln.models.substance import Substance
from stoic_eln.models.supplier import Supplier
from stoic_eln.models.user import User


def _login(client, username, password="x"):
    r = client.get("/auth/login")
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', r.data)
    csrf = m.group(1).decode() if m else ""
    return client.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "username": username,
            "password": password,
            "submit": "x",
        },
    )


def _csrf(client) -> str:
    r = client.get("/")
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', r.data)
    return m.group(1).decode() if m else ""


@pytest.fixture
def admin_user(app):
    with app.app_context():
        u = User(
            username="ric",
            full_name="Riccardo",
            operator_code="RIC",
            role="admin",
            is_admin=True,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
        return u.id


def test_create_supplier(app, client, admin_user):
    """Creating a supplier via POST does not raise and persists data."""
    _login(client, "ric")
    csrf = _csrf(client)

    r = client.post(
        "/suppliers/new",
        data={
            "csrf_token": csrf,
            "name": "Sigma-Aldrich",
            "email": "orders@sigma.example",
            "phone": "+49 30 1234567",
            "url": "https://www.sigmaaldrich.com",
            "portal_username": "labuser",
            "portal_password": "secret123",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302

    with app.app_context():
        s = db.session.query(Supplier).filter_by(name="Sigma-Aldrich").first()
        assert s is not None
        assert s.email == "orders@sigma.example"
        assert s.portal_password == "secret123"


def test_create_supplier_requires_name(app, client, admin_user):
    """Empty name is rejected, no supplier created."""
    _login(client, "ric")
    csrf = _csrf(client)

    r = client.post(
        "/suppliers/new",
        data={"csrf_token": csrf, "name": ""},
        follow_redirects=False,
    )
    assert r.status_code == 200  # re-renders form, no redirect
    with app.app_context():
        assert db.session.query(Supplier).count() == 0


def test_duplicate_supplier_name_rejected(app, client, admin_user):
    """Two suppliers cannot share the same name."""
    _login(client, "ric")
    csrf = _csrf(client)

    with app.app_context():
        db.session.add(Supplier(name="TCI"))
        db.session.commit()

    r = client.post(
        "/suppliers/new",
        data={"csrf_token": csrf, "name": "TCI"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    with app.app_context():
        assert db.session.query(Supplier).filter_by(name="TCI").count() == 1


def test_edit_supplier(app, client, admin_user):
    """Editing updates fields and does not raise."""
    _login(client, "ric")
    csrf = _csrf(client)

    with app.app_context():
        s = Supplier(name="VWR")
        db.session.add(s)
        db.session.commit()
        sid = s.id

    r = client.post(
        f"/suppliers/{sid}/edit",
        data={"csrf_token": csrf, "name": "VWR International", "phone": "123"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    with app.app_context():
        s = db.session.get(Supplier, sid)
        assert s.name == "VWR International"
        assert s.phone == "123"


def test_delete_supplier_detaches_orders(app, client, admin_user):
    """Deleting a supplier sets supplier_id to NULL on linked orders
    but does not delete the orders themselves."""
    _login(client, "ric")
    csrf = _csrf(client)

    with app.app_context():
        from stoic_eln.models.group import Group

        group = db.session.query(Group).first()
        if group is None:
            group = Group(name="default", slug="default")
            db.session.add(group)
            db.session.flush()

        sub = Substance(name="Test substance", molecular_weight=100.0, state="solid")
        db.session.add(sub)
        db.session.flush()

        s = Supplier(name="Merck")
        db.session.add(s)
        db.session.flush()

        order = Order(
            substance_id=sub.id,
            group_id=group.id,
            supplier_id=s.id,
            ordered_quantity_g=10.0,
            created_by_id=admin_user,
        )
        db.session.add(order)
        db.session.commit()
        sid = s.id
        oid = order.id

    r = client.post(f"/suppliers/{sid}/delete", data={"csrf_token": csrf})
    assert r.status_code == 302

    with app.app_context():
        assert db.session.get(Supplier, sid) is None
        order = db.session.get(Order, oid)
        assert order is not None
        assert order.supplier_id is None


def test_supplier_detail_page(app, client, admin_user):
    """Detail page renders without error for a supplier with no orders."""
    _login(client, "ric")
    with app.app_context():
        s = Supplier(name="Fisher Scientific")
        db.session.add(s)
        db.session.commit()
        sid = s.id

    r = client.get(f"/suppliers/{sid}")
    assert r.status_code == 200
    assert b"Fisher Scientific" in r.data


def test_supplier_list_page(app, client, admin_user):
    """List page renders without error."""
    _login(client, "ric")
    r = client.get("/suppliers/")
    assert r.status_code == 200


def test_supplier_orders_is_list_not_none(app, admin_user):
    """Regression: Supplier.orders must be a list (possibly empty),
    never None. A bare `Mapped[list]` annotation without a type
    parameter previously confused SQLAlchemy's uselist inference."""
    with app.app_context():
        s = Supplier(name="Empty Orders Co")
        db.session.add(s)
        db.session.commit()
        assert s.orders is not None
        assert s.orders == []
        assert len(s.orders) == 0
