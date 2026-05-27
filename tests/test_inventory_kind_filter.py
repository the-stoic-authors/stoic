"""Tests for the inventory ``kind`` filter (Substance / Mixture / Solvent).

The /inventory/ list view supports a ``?kind=`` query parameter with
four values:
  - ``all``       — no kind restriction (default)
  - ``substance`` — only InventoryItem rows where substance_id is set
  - ``mixture``   — only InventoryItem rows where mixture_id is set
  - ``solvent``   — strict subset of substance lots whose Substance has
                    ``is_solvent=True``. Mixtures are never returned
                    under this filter because they have no
                    ``is_solvent`` equivalent.

These tests build a 4-lot inventory (one solid, one solvent, one
mixture, one second mixture) and verify each filter narrows the
result correctly.
"""

from __future__ import annotations

from datetime import date

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    InventoryItem,
    Mixture,
    Substance,
    User,
)
from stoic_eln.models.mixture import MIXTURE_KIND_SOLUTION


# ── Fixture helper ──────────────────────────────────────────────────


def _setup_mixed_inventory():
    """Create 4 lots: 1 plain substance, 1 solvent substance, 2 mixtures.

    Returns a dict of ids for the test to assert against. Must be
    called inside ``app.app_context()``.
    """
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

    g = Group(name="L", slug="l", is_default=True, is_active=True)
    db.session.add(g)

    # Substance #1: a "normal" reagent
    s_reagent = Substance(
        name="CuBr2",
        molecular_weight=223.35,
        is_solvent=False,
    )
    # Substance #2: a solvent (e.g. EtOAc)
    s_solvent = Substance(
        name="EtOAc",
        molecular_weight=88.11,
        is_solvent=True,
        density=0.902,
    )
    # Mixture #1: commercial solution
    m_hcl = Mixture(
        name="HCl",
        kind=MIXTURE_KIND_SOLUTION,
        primary_concentration=12.0,
        primary_concentration_unit="N",
    )
    # Mixture #2: another commercial solution
    m_naoh = Mixture(
        name="NaOH",
        kind=MIXTURE_KIND_SOLUTION,
        primary_concentration=1.0,
        primary_concentration_unit="M",
    )
    db.session.add_all([s_reagent, s_solvent, m_hcl, m_naoh])
    db.session.commit()

    # One lot per entity
    lot_reagent = InventoryItem(
        substance_id=s_reagent.id,
        group_id=g.id,
        batch_code="CB001",
        quantity_g=50.0,
        initial_quantity_g=50.0,
        purchased_at=date.today(),
        is_active=True,
    )
    lot_solvent = InventoryItem(
        substance_id=s_solvent.id,
        group_id=g.id,
        batch_code="EA001",
        quantity_mL=1000.0,
        initial_quantity_mL=1000.0,
        purchased_at=date.today(),
        is_active=True,
    )
    lot_hcl = InventoryItem(
        mixture_id=m_hcl.id,
        group_id=g.id,
        batch_code="HCL001",
        quantity_mL=500.0,
        initial_quantity_mL=500.0,
        purchased_at=date.today(),
        is_active=True,
    )
    lot_naoh = InventoryItem(
        mixture_id=m_naoh.id,
        group_id=g.id,
        batch_code="NAOH001",
        quantity_mL=250.0,
        initial_quantity_mL=250.0,
        purchased_at=date.today(),
        is_active=True,
    )
    db.session.add_all([lot_reagent, lot_solvent, lot_hcl, lot_naoh])
    db.session.commit()

    return {
        "user_id": u.id,
        "lot_reagent_id": lot_reagent.id,
        "lot_solvent_id": lot_solvent.id,
        "lot_hcl_id": lot_hcl.id,
        "lot_naoh_id": lot_naoh.id,
    }


def _login(client):
    client.post(
        "/auth/login",
        data={"username": "r", "password": "x", "submit": "x"},
    )


# ── Tests ───────────────────────────────────────────────────────────


def test_inventory_kind_all_shows_everything(app, client):
    """kind=all (default) returns all 4 lots."""
    with app.app_context():
        _setup_mixed_inventory()

    _login(client)
    r = client.get("/inventory/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # All four lots' codes appear
    assert "CB001" in body
    assert "EA001" in body
    assert "HCL001" in body
    assert "NAOH001" in body


def test_inventory_kind_substance_excludes_mixtures(app, client):
    """kind=substance keeps both substance lots (reagent + solvent)
    and excludes mixture lots."""
    with app.app_context():
        _setup_mixed_inventory()

    _login(client)
    r = client.get("/inventory/?kind=substance")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "CB001" in body
    assert "EA001" in body  # Solvent IS a substance — included
    assert "HCL001" not in body
    assert "NAOH001" not in body


def test_inventory_kind_mixture_only_mixtures(app, client):
    """kind=mixture keeps mixture lots only."""
    with app.app_context():
        _setup_mixed_inventory()

    _login(client)
    r = client.get("/inventory/?kind=mixture")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "CB001" not in body
    assert "EA001" not in body
    assert "HCL001" in body
    assert "NAOH001" in body


def test_inventory_kind_solvent_only_solvent_substances(app, client):
    """kind=solvent is a strict subset of substance lots — only those
    whose Substance has is_solvent=True. Mixtures are NEVER shown
    under this filter."""
    with app.app_context():
        _setup_mixed_inventory()

    _login(client)
    r = client.get("/inventory/?kind=solvent")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "CB001" not in body  # reagent: not a solvent
    assert "EA001" in body  # EtOAc IS a solvent
    assert "HCL001" not in body  # Mixture excluded
    assert "NAOH001" not in body  # Mixture excluded


def test_inventory_kind_invalid_falls_back_to_all(app, client):
    """Unknown kind values are normalised to 'all'."""
    with app.app_context():
        _setup_mixed_inventory()

    _login(client)
    r = client.get("/inventory/?kind=banana")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Same as kind=all
    assert "CB001" in body
    assert "EA001" in body
    assert "HCL001" in body
    assert "NAOH001" in body


def test_inventory_kind_combines_with_other_filters(app, client):
    """kind filter composes with text search q."""
    with app.app_context():
        _setup_mixed_inventory()

    _login(client)
    # Search for "HCL" with kind=mixture → only HCL001
    r = client.get("/inventory/?kind=mixture&q=HCL")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "HCL001" in body
    assert "NAOH001" not in body  # other mixture excluded by q
    assert "CB001" not in body
    assert "EA001" not in body
