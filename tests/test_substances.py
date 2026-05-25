"""Tests for substance and inventory blueprints + models."""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.substance import Substance


# ─── Model tests ─────────────────────────────────────────────────────────────


def test_substance_create(app):
    with app.app_context():
        sub = Substance(name="Test compound", molecular_weight=100.0, smiles="CCO")
        db.session.add(sub)
        db.session.commit()
        assert sub.id is not None
        assert sub.display_name == "Test compound"
        assert sub.is_active is True


def test_substance_inchi_key_unique(app):
    with app.app_context():
        a = Substance(name="A", inchi_key="LFQSCWFLJHTTHZ-UHFFFAOYSA-N")
        db.session.add(a)
        db.session.commit()

        b = Substance(name="B", inchi_key="LFQSCWFLJHTTHZ-UHFFFAOYSA-N")
        db.session.add(b)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


def test_substance_detect_state(app):
    with app.app_context():
        # Liquid: MP < 25 < BP
        sub = Substance(name="EtOH-like", melting_point_c=-100.0, boiling_point_c=78.0)
        assert sub.detect_state() == "liquid"

        # Solid: MP > 25
        sub2 = Substance(name="Solid", melting_point_c=100.0)
        assert sub2.detect_state() == "solid"

        # Gas: BP < 25
        sub3 = Substance(name="Gas", boiling_point_c=-50.0)
        assert sub3.detect_state() == "gas"


def test_substance_total_quantity(app):
    with app.app_context():
        sub = Substance(name="EtOH", is_solvent=True)
        db.session.add(sub)
        db.session.flush()

        item1 = InventoryItem(substance_id=sub.id, quantity_mL=100.0)
        item2 = InventoryItem(substance_id=sub.id, quantity_mL=250.0)
        item3 = InventoryItem(substance_id=sub.id, quantity_mL=50.0, is_active=False)
        db.session.add_all([item1, item2, item3])
        db.session.commit()

        assert sub.total_quantity_mL == 350.0
        assert sub.active_inventory_count == 2


def test_inventory_cost_per_unit(app):
    with app.app_context():
        sub = Substance(name="X")
        db.session.add(sub)
        db.session.flush()

        item = InventoryItem(
            substance_id=sub.id,
            initial_quantity_g=100.0,
            quantity_g=80.0,
            total_cost_eur=50.0,
        )
        assert item.cost_per_unit == pytest.approx(0.5)
        assert item.percent_remaining == pytest.approx(80.0)


def test_inventory_use_quantity(app):
    with app.app_context():
        sub = Substance(name="X")
        db.session.add(sub)
        db.session.flush()
        item = InventoryItem(substance_id=sub.id, quantity_g=100.0)
        assert item.use_quantity(30.0, "g") is True
        assert item.quantity_g == 70.0
        # Insufficient
        assert item.use_quantity(200.0, "g") is False
        assert item.quantity_g == 70.0


# ─── Route tests (require auth) ──────────────────────────────────────────────


def _login(client, app):
    """Helper to create admin and log in."""
    from stoic_eln.models.user import User

    with app.app_context():
        if db.session.query(User).filter_by(username="admin").first() is None:
            u = User(
                username="admin",
                full_name="Admin",
                operator_code="ADM",
                is_admin=True,
                is_active=True,
                locale="it",
            )
            u.set_password("password123")
            db.session.add(u)
            db.session.commit()

    # In tests, CSRF is disabled (TestingConfig), so just POST directly.
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "password123", "submit": "Accedi"},
    )


def test_substances_list_requires_auth(client):
    resp = client.get("/substances/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_substances_list_renders(client, app):
    with app.app_context():
        sub = Substance(name="Caffeine", molecular_formula="C8H10N4O2")
        db.session.add(sub)
        db.session.commit()

    _login(client, app)
    resp = client.get("/substances/")
    assert resp.status_code == 200
    assert b"Caffeine" in resp.data
    assert b"C8H10N4O2" in resp.data


def test_substances_search_filters(client, app):
    with app.app_context():
        db.session.add_all(
            [
                Substance(name="Aspirin", cas_number="50-78-2"),
                Substance(name="Caffeine", cas_number="58-08-2"),
            ]
        )
        db.session.commit()

    _login(client, app)
    resp = client.get("/substances/?q=caffe")
    assert b"Caffeine" in resp.data
    assert b"Aspirin" not in resp.data


def test_substances_search_finds_by_cas(client, app):
    with app.app_context():
        db.session.add(Substance(name="Aspirin", cas_number="50-78-2"))
        db.session.commit()
    _login(client, app)
    resp = client.get("/substances/?q=50-78-2")
    assert b"Aspirin" in resp.data


def test_substances_search_finds_by_batch_code(client, app):
    with app.app_context():
        sub = Substance(name="Mystery solvent")
        db.session.add(sub)
        db.session.flush()
        db.session.add(InventoryItem(substance_id=sub.id, batch_code="STBG3140"))
        db.session.commit()
    _login(client, app)
    resp = client.get("/substances/?q=STBG3140")
    assert b"Mystery solvent" in resp.data


def test_substances_htmx_returns_partial(client, app):
    with app.app_context():
        db.session.add(Substance(name="Foo"))
        db.session.commit()
    _login(client, app)
    resp = client.get("/substances/", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    # Partial should not contain the full <html> doctype
    assert b"<!doctype" not in resp.data.lower()
    assert b"<html" not in resp.data.lower()
    # But should contain the table
    assert b"Foo" in resp.data


def test_substance_detail(client, app):
    with app.app_context():
        sub = Substance(
            name="EtOH",
            cas_number="64-17-5",
            molecular_formula="C2H6O",
            molecular_weight=46.07,
            smiles="CCO",
            inchi_key="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
            ghs_pictograms=["GHS02"],
            h_phrases=["H225"],
        )
        db.session.add(sub)
        db.session.commit()
        sid = sub.id

    _login(client, app)
    resp = client.get(f"/substances/{sid}")
    assert resp.status_code == 200
    assert b"64-17-5" in resp.data
    assert b"GHS02.svg" in resp.data
    assert b"H225" in resp.data


def test_substance_create_form(client, app):
    _login(client, app)
    resp = client.get("/substances/new")
    assert resp.status_code == 200
    assert b"Nome" in resp.data or b"Name" in resp.data


def test_substance_create_post(client, app):
    _login(client, app)
    resp = client.post(
        "/substances/new",
        data={
            "name": "Methanol",
            "cas_number": "67-56-1",
            "molecular_formula": "CH4O",
            "molecular_weight": "32.04",
            "submit": "Salva",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        sub = db.session.query(Substance).filter_by(name="Methanol").first()
        assert sub is not None
        assert sub.cas_number == "67-56-1"


def test_substance_duplicate_inchi_key_blocks_create(client, app):
    """Creating a substance with an InChIKey that already exists redirects to existing one."""
    with app.app_context():
        existing = Substance(name="Original", inchi_key="LFQSCWFLJHTTHZ-UHFFFAOYSA-N")
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

    _login(client, app)
    resp = client.post(
        "/substances/new",
        data={
            "name": "Duplicate",
            "inchi_key": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
            "submit": "Salva",
        },
        follow_redirects=False,
    )
    # Should redirect to the existing entry
    assert resp.status_code == 302
    assert f"/substances/{existing_id}" in resp.headers["Location"]
    # And no duplicate was created
    with app.app_context():
        count = (
            db.session.query(Substance).filter_by(inchi_key="LFQSCWFLJHTTHZ-UHFFFAOYSA-N").count()
        )
        assert count == 1


# ─── Inventory routes ────────────────────────────────────────────────────────


def test_inventory_list_renders(client, app):
    with app.app_context():
        sub = Substance(name="EtOH")
        db.session.add(sub)
        db.session.flush()
        db.session.add(
            InventoryItem(
                substance_id=sub.id,
                batch_code="LOT001",
                supplier="Sigma",
                quantity_mL=500.0,
                location="Armadio 3",
            )
        )
        db.session.commit()

    _login(client, app)
    resp = client.get("/inventory/")
    assert resp.status_code == 200
    assert b"LOT001" in resp.data
    assert b"Sigma" in resp.data
    assert b"Armadio 3" in resp.data


def test_inventory_add_lot(client, app):
    with app.app_context():
        sub = Substance(name="EtOH")
        db.session.add(sub)
        db.session.commit()
        sid = sub.id

    _login(client, app)
    resp = client.get(f"/inventory/substance/{sid}/new")
    assert resp.status_code == 200

    resp = client.post(
        f"/inventory/substance/{sid}/new",
        data={
            "batch_code": "BATCH-001",
            "supplier": "Sigma-Aldrich",
            "initial_quantity_mL": "1000",
            "total_cost_eur": "75.50",
            "location": "Frigo lab2",
            "is_active": "y",
            "submit": "Salva",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        item = db.session.query(InventoryItem).filter_by(batch_code="BATCH-001").first()
        assert item is not None
        assert item.supplier == "Sigma-Aldrich"
        assert item.initial_quantity_mL == 1000.0
        # quantity_mL should default to initial since it was empty
        assert item.quantity_mL == 1000.0
