"""Tests for the inventory g/mL unit policy.

Two layers:

1. **Service layer** (``inventory_quantity``): exhaustive tests of
   the matrix for the four substance categories — reagent solid,
   reagent with density, solvent without density, solvent with
   density — applied to both initial and remaining pairs, plus the
   consistency check for dual-synced rows.

2. **Route layer** (``inventory.create`` / ``inventory.edit``):
   smoke tests verifying that the policy is enforced on submit
   (auto-fill of the missing unit, validation error for the wrong
   unit, etc.).
"""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import Group, InventoryItem, Substance, User
from stoic_eln.services.inventory_quantity import (
    normalize_inventory_quantities,
    normalize_pair,
    policy_for_substance,
)


def _load_cleanup_main():
    """Load ``cleanup_mL_on_solid_substances.main`` by file path.

    The ``scripts/`` directory intentionally isn't a Python package
    (no ``__init__.py``): scripts in there are standalone utilities
    meant to be run via ``python -m`` from the project root, not
    imported by other code. To exercise their logic from tests we
    load the module by file path, which decouples us from the
    quirks of namespace-package discovery (which behaves differently
    on different Python invocations).
    """
    import importlib.util
    from pathlib import Path

    script_path = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "cleanup_mL_on_solid_substances.py"
    )
    spec = importlib.util.spec_from_file_location(
        "cleanup_mL_on_solid_substances", script_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


# ── Fixtures ────────────────────────────────────────────────────────


def _solid_no_density() -> Substance:
    """A typical reagent solid (sodium chloride class)."""
    return Substance(name="NaCl", molecular_weight=58.44)


def _reagent_with_density() -> Substance:
    """Liquid reagent with density (e.g. hexanoyl chloride)."""
    return Substance(
        name="Hexanoyl chloride",
        molecular_weight=134.6,
        density=0.9763,
    )


def _solvent_no_density() -> Substance:
    """Edge case: marked as solvent but density not entered yet."""
    return Substance(name="MysterySolvent", is_solvent=True)


def _solvent_with_density() -> Substance:
    """Standard solvent (e.g. ethyl acetate)."""
    return Substance(
        name="EtOAc",
        molecular_weight=88.11,
        density=0.902,
        is_solvent=True,
    )


# ── Policy classification ──────────────────────────────────────────


def test_policy_reagent_no_density():
    p = policy_for_substance(_solid_no_density())
    assert p.allow_g is True
    assert p.allow_mL is False
    assert p.synced is False
    assert p.is_solid_or_no_density is True


def test_policy_reagent_with_density():
    p = policy_for_substance(_reagent_with_density())
    assert p.allow_g is True
    assert p.allow_mL is True
    assert p.synced is True
    assert p.density == pytest.approx(0.9763)


def test_policy_solvent_no_density():
    p = policy_for_substance(_solvent_no_density())
    assert p.allow_g is False
    assert p.allow_mL is True
    assert p.synced is False
    assert p.is_solvent_no_density is True


def test_policy_solvent_with_density():
    p = policy_for_substance(_solvent_with_density())
    assert p.allow_g is True
    assert p.allow_mL is True
    assert p.synced is True


def test_policy_none_substance_is_permissive():
    """For mixture lots (no substance), we want permissive defaults
    so callers that aren't aware of the matrix don't break."""
    p = policy_for_substance(None)
    assert p.allow_g is True
    assert p.allow_mL is True
    assert p.synced is False


def test_policy_zero_density_treated_as_unset():
    """Density 0 (or negative) shouldn't sync — protects against
    arithmetic errors on bad data."""
    s = Substance(name="X", density=0)
    p = policy_for_substance(s)
    assert p.synced is False


# ── normalize_pair — substance side ────────────────────────────────


def test_normalize_reagent_no_density_g_only():
    p = policy_for_substance(_solid_no_density())
    g, mL, err = normalize_pair(100.0, None, p)
    assert (g, mL, err) == (100.0, None, None)


def test_normalize_reagent_no_density_rejects_mL():
    p = policy_for_substance(_solid_no_density())
    g, mL, err = normalize_pair(None, 50.0, p)
    assert err is not None and "grammi" in err.lower()


def test_normalize_reagent_with_density_fills_mL_from_g():
    p = policy_for_substance(_reagent_with_density())
    g, mL, err = normalize_pair(100.0, None, p)
    assert err is None
    assert g == 100.0
    assert mL == pytest.approx(100.0 / 0.9763, rel=1e-3)


def test_normalize_reagent_with_density_fills_g_from_mL():
    p = policy_for_substance(_reagent_with_density())
    g, mL, err = normalize_pair(None, 100.0, p)
    assert err is None
    assert mL == 100.0
    assert g == pytest.approx(97.63, rel=1e-3)


def test_normalize_reagent_with_density_both_set_consistent():
    p = policy_for_substance(_reagent_with_density())
    g, mL, err = normalize_pair(100.0, 102.43, p)
    assert err is None


def test_normalize_reagent_with_density_both_set_inconsistent():
    p = policy_for_substance(_reagent_with_density())
    g, mL, err = normalize_pair(100.0, 50.0, p)
    assert err is not None
    assert "incoerenti" in err.lower()


def test_normalize_solvent_no_density_mL_only():
    p = policy_for_substance(_solvent_no_density())
    g, mL, err = normalize_pair(None, 500.0, p)
    assert (g, mL, err) == (None, 500.0, None)


def test_normalize_solvent_no_density_rejects_g():
    p = policy_for_substance(_solvent_no_density())
    g, mL, err = normalize_pair(100.0, None, p)
    assert err is not None and "millilitri" in err.lower()


def test_normalize_solvent_with_density_fills_both_ways():
    p = policy_for_substance(_solvent_with_density())
    # From g
    g, mL, err = normalize_pair(100.0, None, p)
    assert err is None
    assert mL == pytest.approx(100.0 / 0.902, rel=1e-3)
    # From mL
    g, mL, err = normalize_pair(None, 100.0, p)
    assert err is None
    assert g == pytest.approx(90.2, rel=1e-3)


def test_normalize_both_empty_is_fine():
    """An empty pair is valid (lot with no quantity yet)."""
    for sub_fn in (
        _solid_no_density,
        _reagent_with_density,
        _solvent_no_density,
        _solvent_with_density,
    ):
        p = policy_for_substance(sub_fn())
        g, mL, err = normalize_pair(None, None, p)
        assert err is None
        assert g is None and mL is None


# ── normalize_inventory_quantities — full lot ──────────────────────


def test_full_normalize_propagates_initial_and_remaining():
    """Both initial and remaining pairs are normalised."""
    sub = _reagent_with_density()
    init_g, init_mL, rem_g, rem_mL, err = normalize_inventory_quantities(
        initial_g=100.0,
        initial_mL=None,
        remaining_g=50.0,
        remaining_mL=None,
        substance=sub,
    )
    assert err is None
    assert init_g == 100.0
    assert init_mL == pytest.approx(100.0 / 0.9763, rel=1e-3)
    assert rem_g == 50.0
    assert rem_mL == pytest.approx(50.0 / 0.9763, rel=1e-3)


def test_full_normalize_error_on_initial_short_circuits():
    """An error on the initial pair is returned without checking
    remaining (clearer UX: one error at a time)."""
    sub = _solid_no_density()
    init_g, init_mL, rem_g, rem_mL, err = normalize_inventory_quantities(
        initial_g=100.0,
        initial_mL=50.0,  # mL not allowed for reagent-no-density
        remaining_g=None,
        remaining_mL=None,
        substance=sub,
    )
    assert err is not None


# ── Route smoke tests ──────────────────────────────────────────────


def _login(client):
    client.post(
        "/auth/login",
        data={"username": "r", "password": "x", "submit": "x"},
    )


def _admin_and_group():
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
    g = Group(name="L", slug="l", is_default=True, is_active=True)
    db.session.add_all([u, g])
    db.session.commit()
    return u.id, g.id


def test_route_create_reagent_with_density_auto_fills_mL(app, client):
    """Submitting a lot of a reagent-with-density with only g set
    must auto-populate mL via density."""
    with app.app_context():
        _admin_and_group()
        sub = _reagent_with_density()
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

    _login(client)
    resp = client.post(
        f"/inventory/new?substance_id={sub_id}",
        data={
            "initial_quantity_g": "100",
            "quantity_g": "100",
            "is_active": "y",
            "submit": "Salva",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    with app.app_context():
        item = db.session.query(InventoryItem).filter(InventoryItem.substance_id == sub_id).first()
        assert item is not None
        assert item.initial_quantity_g == pytest.approx(100.0)
        assert item.initial_quantity_mL == pytest.approx(100.0 / 0.9763, rel=1e-3)
        assert item.quantity_g == pytest.approx(100.0)
        assert item.quantity_mL == pytest.approx(100.0 / 0.9763, rel=1e-3)


def test_route_create_reagent_no_density_rejects_mL(app, client):
    """Submitting mL on a reagent without density must be refused
    with a flash error and no item saved."""
    with app.app_context():
        _admin_and_group()
        sub = _solid_no_density()
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

    _login(client)
    resp = client.post(
        f"/inventory/new?substance_id={sub_id}",
        data={
            "initial_quantity_g": "",
            "initial_quantity_mL": "50",
            "quantity_g": "",
            "quantity_mL": "",
            "is_active": "y",
            "submit": "Salva",
        },
        follow_redirects=False,
    )
    # Form re-rendered (200), not redirected (302/303)
    assert resp.status_code == 200

    with app.app_context():
        items = db.session.query(InventoryItem).filter(InventoryItem.substance_id == sub_id).all()
        assert items == []


def test_route_create_solvent_no_density_rejects_g(app, client):
    """A solvent without density must refuse a g entry."""
    with app.app_context():
        _admin_and_group()
        sub = _solvent_no_density()
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

    _login(client)
    resp = client.post(
        f"/inventory/new?substance_id={sub_id}",
        data={
            "initial_quantity_g": "100",
            "quantity_g": "",
            "quantity_mL": "",
            "is_active": "y",
            "submit": "Salva",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    with app.app_context():
        items = db.session.query(InventoryItem).filter(InventoryItem.substance_id == sub_id).all()
        assert items == []


def test_route_create_inconsistent_both_set_rejected(app, client):
    """A dual-synced substance with both values set inconsistent
    must be rejected — not silently overridden."""
    with app.app_context():
        _admin_and_group()
        sub = _reagent_with_density()
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

    _login(client)
    resp = client.post(
        f"/inventory/new?substance_id={sub_id}",
        data={
            "initial_quantity_g": "100",
            "initial_quantity_mL": "50",  # ≠ 100/0.9763 ≈ 102.43
            "quantity_g": "",
            "quantity_mL": "",
            "is_active": "y",
            "submit": "Salva",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    with app.app_context():
        items = db.session.query(InventoryItem).filter(InventoryItem.substance_id == sub_id).all()
        assert items == []


# ── Physical-state check: density alone is not enough ──────────────


def test_policy_solid_with_density_treated_as_no_density():
    """Sodium sulphate has a real density (~2.66 g/cm³) but MP is
    884°C. At room temperature it's a solid powder, not a liquid.
    The policy must ignore the density and behave as if it were
    a reagent without density (g only)."""
    sub = Substance(
        name="Na2SO4",
        molecular_weight=142.04,
        density=2.66,
        melting_point_c=884.0,
    )
    p = policy_for_substance(sub)
    assert p.allow_g is True
    assert p.allow_mL is False
    assert p.synced is False
    assert p.reason == "reagent_no_density"


def test_policy_solvent_flag_does_not_override_solid_state():
    """A solvent is by chemical definition a liquid at the temperature
    of use. If a substance has MP above room temperature, it is NOT
    a usable solvent (it would be a melt or an alloy). Setting
    ``is_solvent=True`` on a solid is therefore a catalog error and
    must NOT bypass the state check.

    Concretely: naphthalene flagged is_solvent=True with density 1.0
    and MP 80°C is treated as a "solvent without density" (mL only,
    no sync) — same as any other solvent whose density wasn't usable.
    """
    sub = Substance(
        name="NaphthaleneTagged",
        is_solvent=True,
        density=1.0,
        melting_point_c=80.0,  # solid at 25°C
    )
    p = policy_for_substance(sub)
    # is_solvent + density-effectively-None → solvent_no_density
    assert p.allow_g is False
    assert p.allow_mL is True
    assert p.synced is False
    assert p.reason == "solvent_no_density"


def test_policy_low_mp_liquid_keeps_density():
    """A normal room-temperature liquid (e.g. hexanoyl chloride,
    MP -90, BP 123) must stay dual-synced."""
    sub = Substance(
        name="HexCl",
        molecular_weight=134.6,
        density=0.9763,
        melting_point_c=-90.0,
        boiling_point_c=123.0,
    )
    p = policy_for_substance(sub)
    assert p.synced is True
    assert p.allow_g is True
    assert p.allow_mL is True


def test_policy_density_without_mp_assumed_intentional():
    """If the substance has density but no MP/BP recorded, we trust
    that whoever set the density did so deliberately (e.g. for a
    liquid where the operator didn't fill in MP). We don't penalise
    incomplete catalog entries."""
    sub = Substance(name="LiquidX", density=1.2)
    p = policy_for_substance(sub)
    assert p.synced is True


def test_policy_borderline_mp_at_threshold():
    """A substance with MP exactly at 25°C is borderline; detect_state
    returns 'liquid' (covers the closed interval). Dose-in-mL stays
    enabled — this matches the behaviour of detect_state which uses
    a <= comparison."""
    sub = Substance(
        name="Borderline",
        density=1.0,
        melting_point_c=25.0,
        boiling_point_c=100.0,
    )
    p = policy_for_substance(sub)
    # detect_state returns 'liquid' because 25 <= 25 <= 100
    assert p.synced is True


# ── Cleanup script ─────────────────────────────────────────────────


def test_cleanup_script_clears_mL_on_solid_substances(app):
    """The cleanup script restores g-only state to lots whose substance
    is now classified as solid under the post-fix policy."""
    with app.app_context():
        # Simulate the situation left by the earlier over-eager migration:
        # a solid (Na2SO4) lot with both g and mL populated (mL = g/density).
        g_obj = Group(name="L", slug="l")
        s_solid = Substance(
            name="Na2SO4",
            molecular_weight=142.04,
            density=2.66,
            melting_point_c=884.0,
        )
        s_liquid = Substance(
            name="HexCl",
            molecular_weight=134.6,
            density=0.9763,
            melting_point_c=-90.0,
            boiling_point_c=123.0,
        )
        db.session.add_all([g_obj, s_solid, s_liquid])
        db.session.commit()

        # Solid lot — both populated, mL must be cleared
        lot_solid = InventoryItem(
            substance_id=s_solid.id,
            group_id=g_obj.id,
            batch_code="NaSO4-001",
            initial_quantity_g=100.0,
            initial_quantity_mL=100.0 / 2.66,
            quantity_g=80.0,
            quantity_mL=80.0 / 2.66,
            is_active=True,
        )
        # Liquid lot — must NOT be touched
        lot_liquid = InventoryItem(
            substance_id=s_liquid.id,
            group_id=g_obj.id,
            batch_code="HEX-001",
            initial_quantity_g=100.0,
            initial_quantity_mL=100.0 / 0.9763,
            quantity_g=80.0,
            quantity_mL=80.0 / 0.9763,
            is_active=True,
        )
        db.session.add_all([lot_solid, lot_liquid])
        db.session.commit()
        solid_id = lot_solid.id
        liquid_id = lot_liquid.id

        cleanup_main = _load_cleanup_main()

        summary = cleanup_main()

        # The solid lot was touched
        assert summary["cleared_mL_only"] == 1
        assert summary["skipped_dosable_in_volume"] == 1

        # Re-read from DB
        ls = db.session.get(InventoryItem, solid_id)
        assert ls.quantity_g == pytest.approx(80.0)  # unchanged
        assert ls.quantity_mL is None  # cleared
        assert ls.initial_quantity_g == pytest.approx(100.0)
        assert ls.initial_quantity_mL is None

        # The liquid lot is untouched
        ll = db.session.get(InventoryItem, liquid_id)
        assert ll.quantity_mL is not None
        assert ll.initial_quantity_mL is not None


def test_cleanup_script_is_idempotent(app):
    """Running the cleanup twice is safe — the second run finds
    nothing to do."""
    with app.app_context():
        g_obj = Group(name="L", slug="l")
        s_solid = Substance(
            name="Na2SO4",
            density=2.66,
            melting_point_c=884.0,
        )
        db.session.add_all([g_obj, s_solid])
        db.session.commit()
        lot = InventoryItem(
            substance_id=s_solid.id,
            group_id=g_obj.id,
            initial_quantity_g=100.0,
            initial_quantity_mL=100.0 / 2.66,
            quantity_g=80.0,
            quantity_mL=80.0 / 2.66,
            is_active=True,
        )
        db.session.add(lot)
        db.session.commit()

        cleanup_main = _load_cleanup_main()

        first = cleanup_main()
        assert first["cleared_mL_only"] == 1

        second = cleanup_main()
        # After cleanup nothing more to do
        assert second["cleared_mL_only"] == 0
        assert second["already_clean"] == 1
