"""Tests for prep_service when a recipe uses child_mixture components.

Scenario: HCl 6N is prepared by diluting HCl 12N. In the recipe of
HCl 6N, the "solute" is a child_mixture pointing at HCl 12N (not a
pure HCl substance). The cascade prep logic must:

  - find candidate lots OF HCl 12N (not lots "containing HCl")
  - read stock concentration from HCl 12N.primary_concentration
  - compute the dilution correctly
  - consume the HCl 12N lot when the prep is executed
  - leave the HCl 12N's own ancestry alone (1-level cascade)

The tests build the HCl 12N → HCl 6N hierarchy explicitly and
exercise each stage.
"""

from __future__ import annotations

from datetime import date

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    InventoryItem,
    Mixture,
    Substance,
    User,
)
from stoic_eln.models.mixture import (
    COMPONENT_ROLE_SOLUTE,
    COMPONENT_ROLE_SOLVENT,
    MIXTURE_KIND_SOLUTION,
    MixtureComponent,
)
from stoic_eln.services.prep_service import (
    ConsumptionInput,
    PrepInput,
    execute_preparation,
    read_stock_for_child_mixture,
    suggest_consumptions,
)


# ── Fixture helper ──────────────────────────────────────────────────


def _setup_hcl_hierarchy():
    """Build the canonical HCl substance, HCl 12N (commercial), HCl 6N
    (prepared by diluting HCl 12N with water).

    Returns ids for the test to use. Must be called inside
    ``app.app_context()``.

    Catalog:
      - Substance: HCl, H2O
      - Mixture: HCl 12N (with HCl substance as solute, H2O as solvent)
      - Mixture: HCl 6N (with HCl 12N as CHILD_MIXTURE solute, H2O
        substance as solvent)
      - 1 lot of HCl 12N (1L commercial)
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

    hcl = Substance(name="HCl", molecular_weight=36.46)
    water = Substance(name="H2O", molecular_weight=18.02, is_solvent=True)
    db.session.add_all([hcl, water])
    db.session.commit()

    hcl_12n = Mixture(
        name="HCl 12N",
        kind=MIXTURE_KIND_SOLUTION,
        primary_concentration=12.0,
        primary_concentration_unit="N",
    )
    hcl_12n.components = [
        MixtureComponent(
            substance_id=hcl.id,
            role=COMPONENT_ROLE_SOLUTE,
            concentration=12.0,
            concentration_unit="N",
        ),
        MixtureComponent(
            substance_id=water.id,
            role=COMPONENT_ROLE_SOLVENT,
        ),
    ]
    db.session.add(hcl_12n)
    db.session.commit()

    # HCl 6N is prepared from HCl 12N (child_mixture)
    hcl_6n = Mixture(
        name="HCl 6N",
        kind=MIXTURE_KIND_SOLUTION,
        primary_concentration=6.0,
        primary_concentration_unit="N",
    )
    hcl_6n.components = [
        MixtureComponent(
            child_mixture_id=hcl_12n.id,
            role=COMPONENT_ROLE_SOLUTE,
        ),
        MixtureComponent(
            substance_id=water.id,
            role=COMPONENT_ROLE_SOLVENT,
        ),
    ]
    db.session.add(hcl_6n)
    db.session.commit()

    # One lot of HCl 12N — 1L, commercial
    lot_hcl_12n = InventoryItem(
        mixture_id=hcl_12n.id,
        group_id=g.id,
        batch_code="HCL12-001",
        quantity_mL=1000.0,
        initial_quantity_mL=1000.0,
        total_cost_eur=42.50,
        purchased_at=date(2026, 1, 15),
        is_active=True,
    )
    db.session.add(lot_hcl_12n)
    db.session.commit()

    return {
        "hcl_id": hcl.id,
        "water_id": water.id,
        "hcl_12n_id": hcl_12n.id,
        "hcl_6n_id": hcl_6n.id,
        "lot_hcl_12n_id": lot_hcl_12n.id,
        "group_id": g.id,
    }


# ── Suggest with child_mixture solute ───────────────────────────────


def test_suggest_renders_without_attribute_error_for_child_mixture_recipe(app):
    """The original bug: prepare_form on a recipe with child_mixture
    component raised AttributeError because the code path accessed
    ``comp.substance.name`` on a row where substance was None. After
    the fix, suggest_consumptions must complete cleanly."""
    with app.app_context():
        ids = _setup_hcl_hierarchy()

        # Should not raise
        result = suggest_consumptions(
            mixture=db.session.get(Mixture, ids["hcl_6n_id"]),
            target_quantity=500.0,
            target_unit="mL",
        )

        # Both components must appear in rows
        assert len(result.rows) == 2
        names = {r.display_name for r in result.rows}
        # The solute row should show "HCl 12N (12 N)" or similar
        # (it uses Mixture.display_label)
        assert any("HCl 12N" in n for n in names)
        # The solvent row is plain water
        assert any("H2O" in n for n in names)


def test_suggest_finds_child_mixture_lot_as_candidate(app):
    """The solute row of HCl 6N must propose the HCl 12N lot, not a
    pure-HCl substance lot."""
    with app.app_context():
        ids = _setup_hcl_hierarchy()

        result = suggest_consumptions(
            mixture=db.session.get(Mixture, ids["hcl_6n_id"]),
            target_quantity=500.0,
            target_unit="mL",
        )

        solute_row = next(r for r in result.rows if r.role == COMPONENT_ROLE_SOLUTE)
        assert solute_row.is_mixture is True
        assert solute_row.mixture_id == ids["hcl_12n_id"]
        assert solute_row.substance_id is None
        assert solute_row.suggested_lot_id == ids["lot_hcl_12n_id"]


def test_suggest_dilution_math_uses_child_mixture_primary_concentration(app):
    """For HCl 6N from HCl 12N, the math is:
    V_stock = V_target × C_target / C_stock = 500 × 6/12 = 250 mL
    """
    with app.app_context():
        ids = _setup_hcl_hierarchy()

        result = suggest_consumptions(
            mixture=db.session.get(Mixture, ids["hcl_6n_id"]),
            target_quantity=500.0,
            target_unit="mL",
        )

        solute_row = next(r for r in result.rows if r.role == COMPONENT_ROLE_SOLUTE)
        solvent_row = next(r for r in result.rows if r.role == COMPONENT_ROLE_SOLVENT)

        # 500 mL × 6/12 = 250 mL of HCl 12N
        assert solute_row.suggested_quantity == pytest.approx(250.0)
        assert solute_row.suggested_unit == "mL"
        # Remainder: 500 - 250 = 250 mL of water
        assert solvent_row.suggested_quantity == pytest.approx(250.0)
        assert solvent_row.suggested_unit == "mL"


def test_suggest_stock_info_includes_child_mixture_name(app):
    """The stock_info on the solute row should mention HCl 12N so
    the operator sees which stock the dilution is based on."""
    with app.app_context():
        ids = _setup_hcl_hierarchy()

        result = suggest_consumptions(
            mixture=db.session.get(Mixture, ids["hcl_6n_id"]),
            target_quantity=500.0,
            target_unit="mL",
        )

        solute_row = next(r for r in result.rows if r.role == COMPONENT_ROLE_SOLUTE)
        assert solute_row.stock_info is not None
        assert solute_row.stock_info.concentration == 12.0
        assert solute_row.stock_info.unit == "N"
        assert "HCl 12N" in solute_row.stock_info.display_text


# ── read_stock_for_child_mixture unit tests ─────────────────────────


def test_read_stock_for_child_mixture_uses_primary_concentration(app):
    """The helper reads child_mixture.primary_concentration."""
    with app.app_context():
        ids = _setup_hcl_hierarchy()
        hcl_12n = db.session.get(Mixture, ids["hcl_12n_id"])
        lot = db.session.get(InventoryItem, ids["lot_hcl_12n_id"])

        info = read_stock_for_child_mixture(lot, hcl_12n)
        assert info.concentration == 12.0
        assert info.unit == "N"
        assert info.source == "child_mixture_primary"


def test_read_stock_for_child_mixture_missing_primary_returns_missing(app):
    """If the child_mixture has no primary_concentration set, the
    helper returns a 'missing' StockInfo (config error)."""
    with app.app_context():
        ids = _setup_hcl_hierarchy()
        hcl_12n = db.session.get(Mixture, ids["hcl_12n_id"])
        # Strip the primary concentration to simulate config gap
        hcl_12n.primary_concentration = None
        hcl_12n.primary_concentration_unit = None
        db.session.commit()
        lot = db.session.get(InventoryItem, ids["lot_hcl_12n_id"])

        info = read_stock_for_child_mixture(lot, hcl_12n)
        assert info.concentration is None
        assert info.source == "missing"


# ── consume() actually deducts the child_mixture lot ────────────────


def test_consume_deducts_from_child_mixture_lot(app):
    """Executing a prep that consumes a child_mixture lot must
    decrement that lot's quantity. The cascade is 1-level: no
    ancestor lots are touched."""
    with app.app_context():
        ids = _setup_hcl_hierarchy()
        u = db.session.query(User).first()

        # Prepare 500 mL of HCl 6N — consume 250 mL of HCl 12N lot,
        # plus 250 mL water (water lot doesn't exist in this fixture,
        # but consume() lets you skip components — they're optional
        # at execute time). For simplicity we only feed the solute lot.
        # NB: a real form submission would include both; we mirror
        # that by adding a water lot too.

        # Create a water lot too so consume() doesn't fail on us
        water_lot = InventoryItem(
            substance_id=ids["water_id"],
            group_id=ids["group_id"],
            batch_code="H2O-001",
            quantity_mL=2000.0,
            initial_quantity_mL=2000.0,
            purchased_at=date(2026, 1, 1),
            is_active=True,
        )
        db.session.add(water_lot)
        db.session.commit()
        water_lot_id = water_lot.id

        prep = execute_preparation(
            PrepInput(
                mixture_id=ids["hcl_6n_id"],
                target_quantity=500.0,
                target_quantity_unit="mL",
                consumptions=[
                    ConsumptionInput(
                        inventory_item_id=ids["lot_hcl_12n_id"],
                        quantity_consumed=250.0,
                        quantity_unit="mL",
                    ),
                    ConsumptionInput(
                        inventory_item_id=water_lot_id,
                        quantity_consumed=250.0,
                        quantity_unit="mL",
                    ),
                ],
                output_batch_code=None,
                output_location=None,
                output_expiry_date=None,
                output_notes=None,
                prepared_by_id=u.id,
            )
        )

        assert prep is not None

        # The HCl 12N lot must have been decremented by 250 mL
        lot = db.session.get(InventoryItem, ids["lot_hcl_12n_id"])
        assert lot.quantity_mL == pytest.approx(750.0)  # 1000 - 250

        # And the water lot decremented by 250 mL
        wlot = db.session.get(InventoryItem, water_lot_id)
        assert wlot.quantity_mL == pytest.approx(1750.0)  # 2000 - 250

        # A new lot of HCl 6N was created
        new_lots = (
            db.session.query(InventoryItem)
            .filter(InventoryItem.mixture_id == ids["hcl_6n_id"])
            .all()
        )
        assert len(new_lots) == 1
        assert new_lots[0].quantity_mL == pytest.approx(500.0)


# ── Insufficient quantity raises ValueError ─────────────────────────


def test_consume_raises_on_insufficient_child_mixture_lot(app):
    """If the HCl 12N lot has less than the requested amount,
    consume() raises ValueError — consistent with substance behaviour."""
    with app.app_context():
        ids = _setup_hcl_hierarchy()
        u = db.session.query(User).first()

        # Try to consume 2000 mL from the 1000 mL lot — must fail
        with pytest.raises(ValueError, match="servono.*disponibili"):
            execute_preparation(
                PrepInput(
                    mixture_id=ids["hcl_6n_id"],
                    target_quantity=4000.0,
                    target_quantity_unit="mL",
                    consumptions=[
                        ConsumptionInput(
                            inventory_item_id=ids["lot_hcl_12n_id"],
                            quantity_consumed=2000.0,
                            quantity_unit="mL",
                        ),
                    ],
                    output_batch_code=None,
                    output_location=None,
                    output_expiry_date=None,
                    output_notes=None,
                    prepared_by_id=u.id,
                )
            )

        # Lot must be unchanged after the failed attempt
        lot = db.session.get(InventoryItem, ids["lot_hcl_12n_id"])
        assert lot.quantity_mL == pytest.approx(1000.0)


# ── Mixed purchased_at types (regression test) ──────────────────────


def test_suggest_handles_lots_with_mixed_purchased_at_present_and_none(app):
    """Regression: ``suggest_consumptions`` used to compare
    ``datetime.date`` (purchased_at) and ``datetime.datetime``
    (created_at fallback) in the sort key, raising
    ``TypeError: can't compare datetime.datetime to datetime.date``
    as soon as the candidate set contained one lot with purchased_at
    set and one without.

    The fix uses ``date.min`` as the fallback (matching the pattern
    already in shopping_list service), which keeps the sort key
    homogeneous regardless of whether purchased_at is populated.
    """
    with app.app_context():
        ids = _setup_hcl_hierarchy()
        g = db.session.get(Group, ids["group_id"])
        hcl_12n_id = ids["hcl_12n_id"]

        # The fixture already creates one HCl 12N lot with purchased_at set.
        # Add a second HCl 12N lot WITHOUT a purchase date — this is the
        # combination that used to crash.
        lot2 = InventoryItem(
            mixture_id=hcl_12n_id,
            group_id=g.id,
            batch_code="HCL12-002",
            quantity_mL=500.0,
            initial_quantity_mL=500.0,
            purchased_at=None,  # the trigger
            is_active=True,
        )
        db.session.add(lot2)
        db.session.commit()

        # Must not raise
        hcl_6n = db.session.get(Mixture, ids["hcl_6n_id"])
        result = suggest_consumptions(
            mixture=hcl_6n,
            target_quantity=500.0,
            target_unit="mL",
        )

        # Both lots should appear as candidates for the solute row
        solute_row = next(r for r in result.rows if r.role == COMPONENT_ROLE_SOLUTE)
        assert len(solute_row.available_lots) == 2
