"""Tests for scripts/backfill_mixture_costs.py."""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "scripts")

from backfill_mixture_costs import run_backfill  # noqa: E402

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    InventoryItem,
    Mixture,
    MixtureComponent,
    Substance,
)
from stoic_eln.services.prep_service import (
    ConsumptionInput,
    PrepInput,
    execute_preparation,
)


def _lab():
    g = Group(name="Lab", slug="lab")
    db.session.add(g)
    db.session.flush()
    hcl = Substance(name="HCl", molecular_formula="HCl")
    water = Substance(name="Water", molecular_formula="H2O")
    db.session.add_all([hcl, water])
    db.session.flush()

    def _mix(name, n):
        m = Mixture(
            name=name, kind="solution", primary_concentration=n, primary_concentration_unit="N"
        )
        m.components = [
            MixtureComponent(
                substance_id=hcl.id,
                role="solute",
                concentration=n,
                concentration_unit="N",
                position=0,
            ),
            MixtureComponent(substance_id=water.id, role="solvent", position=1),
        ]
        db.session.add(m)
        db.session.flush()
        return m

    m12, m6, m3 = _mix("HCl 12N", 12), _mix("HCl 6N", 6), _mix("HCl 3N", 3)

    stock_hcl = InventoryItem(
        mixture_id=m12.id,
        group_id=g.id,
        batch_code="HCL12N-001",
        quantity_mL=5000.0,
        initial_quantity_mL=5000.0,
        total_cost_eur=100.0,
        is_active=True,
    )  # 0.02 €/mL
    stock_water = InventoryItem(
        substance_id=water.id,
        group_id=g.id,
        batch_code="H2O-001",
        quantity_mL=20000.0,
        initial_quantity_mL=20000.0,
        total_cost_eur=10.0,
        is_active=True,
    )  # 0.0005 €/mL
    db.session.add_all([stock_hcl, stock_water])
    db.session.commit()
    return dict(m6=m6.id, m3=m3.id, hcl=stock_hcl.id, water=stock_water.id)


def _prep(mixture_id, cons, qty=4.0):
    return execute_preparation(
        PrepInput(
            mixture_id=mixture_id,
            target_quantity=qty,
            target_quantity_unit="L",
            consumptions=cons,
            output_batch_code=None,
            output_location=None,
            output_expiry_date=None,
            output_notes=None,
            prepared_by_id=None,
        )
    )


def test_backfill_prices_a_legacy_mixture_lot(app):
    with app.app_context():
        ctx = _lab()
        prep = _prep(
            ctx["m6"],
            [
                ConsumptionInput(
                    inventory_item_id=ctx["hcl"], quantity_consumed=2.0, quantity_unit="L"
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["water"], quantity_consumed=2.0, quantity_unit="L"
                ),
            ],
        )
        lot_id = prep.output_lot.id
        # simulate a pre-fix lot
        db.session.get(InventoryItem, lot_id).total_cost_eur = None
        db.session.commit()

        s = run_backfill(apply=True)
        assert len(s["priced"]) == 1
        assert db.session.get(InventoryItem, lot_id).total_cost_eur == pytest.approx(41.0)


def test_dry_run_writes_nothing(app):
    with app.app_context():
        ctx = _lab()
        prep = _prep(
            ctx["m6"],
            [
                ConsumptionInput(
                    inventory_item_id=ctx["hcl"], quantity_consumed=2.0, quantity_unit="L"
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["water"], quantity_consumed=2.0, quantity_unit="L"
                ),
            ],
        )
        lot_id = prep.output_lot.id
        db.session.get(InventoryItem, lot_id).total_cost_eur = None
        db.session.commit()

        s = run_backfill(apply=False)
        assert len(s["priced"]) == 1  # it *would* be priced
        assert db.session.get(InventoryItem, lot_id).total_cost_eur is None  # but not written


def test_backfill_chains_mixture_from_mixture(app):
    with app.app_context():
        ctx = _lab()
        # 6N from stocks → lot_6n
        p6 = _prep(
            ctx["m6"],
            [
                ConsumptionInput(
                    inventory_item_id=ctx["hcl"], quantity_consumed=2.0, quantity_unit="L"
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["water"], quantity_consumed=2.0, quantity_unit="L"
                ),
            ],
        )
        lot6 = p6.output_lot.id  # 4 L, cost 41 €
        # 3N from the 6N lot + water → lot_3n
        p3 = _prep(
            ctx["m3"],
            [
                ConsumptionInput(inventory_item_id=lot6, quantity_consumed=2.0, quantity_unit="L"),
                ConsumptionInput(
                    inventory_item_id=ctx["water"], quantity_consumed=2.0, quantity_unit="L"
                ),
            ],
            qty=4.0,
        )
        lot3 = p3.output_lot.id

        # simulate both as pre-fix (no cost)
        db.session.get(InventoryItem, lot6).total_cost_eur = None
        db.session.get(InventoryItem, lot3).total_cost_eur = None
        db.session.commit()

        s = run_backfill(apply=True)
        assert len(s["priced"]) == 2  # both got priced across passes
        c6 = db.session.get(InventoryItem, lot6).total_cost_eur
        c3 = db.session.get(InventoryItem, lot3).total_cost_eur
        assert c6 == pytest.approx(41.0)
        # lot6 is 41 €/4000 mL = 0.01025 €/mL; 2000 mL → 20.5 € + water 2000 mL × 0.0005 = 1 €
        assert c3 == pytest.approx(20.5 + 1.0)
