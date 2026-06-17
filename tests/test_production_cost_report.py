"""Tests for the production-cost report (cumulative vs direct, per substance/batch)."""

from __future__ import annotations

from datetime import datetime

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    InventoryItem,
    Reaction,
    Run,
    RunComponent,
    Substance,
    User,
)
from stoic_eln.models.run import STATUS_COMPLETED
from stoic_eln.services.production_cost_report import compute_production_cost_report


@pytest.fixture()
def admin_user(app):
    with app.app_context():
        u = User(
            username="pc_admin",
            full_name="PC Admin",
            operator_code="PC",
            role="operator",
            is_admin=True,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
        return u.id


def _build_run_with_product():
    """A completed run that consumes one EXTERNAL lot (5 €) and one
    INTERNAL intermediate lot (6 €), and produces 2 g of product P.

    cumulative = 11 €, direct = 5 € → per-g 5.5 / 2.5.
    """
    P = Substance(name="Product-P", molecular_weight=200.0)
    SM = Substance(name="SM-ext", molecular_weight=100.0)
    INT = Substance(name="Intermediate-int", molecular_weight=150.0)
    db.session.add_all([P, SM, INT])
    db.session.flush()

    rxn = Reaction(code="RX-PC", status="published", title="PC")
    db.session.add(rxn)
    db.session.flush()

    # A prior run that "produced" the intermediate (so the int lot is internal).
    prior = Run(
        code="RX-PC-0",
        year=2026,
        sequence=0,
        reaction_id=rxn.id,
        status=STATUS_COMPLETED,
        completed_at=datetime(2026, 1, 1),
    )
    db.session.add(prior)
    db.session.flush()

    sm_lot = InventoryItem(
        substance_id=SM.id,
        total_cost_eur=10.0,
        initial_quantity_g=10.0,
        quantity_g=10.0,
        is_active=True,
    )
    int_lot = InventoryItem(
        substance_id=INT.id,
        total_cost_eur=20.0,
        initial_quantity_g=10.0,
        quantity_g=10.0,
        is_active=True,
        source_run_id=prior.id,
    )  # internal intermediate
    db.session.add_all([sm_lot, int_lot])
    db.session.flush()

    run = Run(
        code="RX-PC-1",
        year=2026,
        sequence=1,
        reaction_id=rxn.id,
        status=STATUS_COMPLETED,
        completed_at=datetime(2026, 3, 1),
        yield_g=2.0,
    )
    db.session.add(run)
    db.session.flush()

    db.session.add_all(
        [
            RunComponent(
                run_id=run.id,
                substance_id=SM.id,
                role="starting_material",
                inventory_item_id=sm_lot.id,
                actual_mass_g=5.0,
                position=0,
                is_limiting=True,
            ),
            RunComponent(
                run_id=run.id,
                substance_id=INT.id,
                role="reactant",
                inventory_item_id=int_lot.id,
                actual_mass_g=3.0,
                position=1,
            ),
            RunComponent(
                run_id=run.id, substance_id=P.id, role="product", actual_mass_g=2.0, position=2
            ),
        ]
    )
    # The produced batch
    db.session.add(
        InventoryItem(
            substance_id=P.id,
            batch_code="RX-PC-1-P1",
            initial_quantity_g=2.0,
            quantity_g=2.0,
            is_active=True,
            source_run_id=run.id,
        )
    )
    db.session.commit()
    return P.id


def test_production_cost_cumulative_vs_direct(app):
    with app.app_context():
        pid = _build_run_with_product()
        report = compute_production_cost_report()

        assert report.has_data
        summ = next(s for s in report.substances if s.substance_id == pid)
        assert summ.batch_count == 1
        assert summ.total_produced_g == pytest.approx(2.0)
        # cumulative 11 €, direct 5 €
        assert summ.total_cost_cumulative == pytest.approx(11.0)
        assert summ.total_cost_direct == pytest.approx(5.0)
        assert summ.avg_per_g_cumulative == pytest.approx(5.5)
        assert summ.avg_per_g_direct == pytest.approx(2.5)

        b = summ.batches[0]
        assert b.batch_code == "RX-PC-1-P1"
        assert b.run_code == "RX-PC-1"
        assert b.per_g_cumulative == pytest.approx(5.5)
        assert b.per_g_direct == pytest.approx(2.5)
        assert b.partial is False


def test_production_report_multi_product_splits_by_mass(app):
    """A run with two product batches splits the run cost by mass."""
    with app.app_context():
        A = Substance(name="Prod-A", molecular_weight=100.0)
        B = Substance(name="Prod-B", molecular_weight=100.0)
        SM = Substance(name="SM2", molecular_weight=100.0)
        db.session.add_all([A, B, SM])
        db.session.flush()
        rxn = Reaction(code="RX-PC2", status="published", title="PC2")
        db.session.add(rxn)
        db.session.flush()
        lot = InventoryItem(
            substance_id=SM.id,
            total_cost_eur=12.0,
            initial_quantity_g=12.0,
            quantity_g=12.0,
            is_active=True,
        )
        db.session.add(lot)
        db.session.flush()
        run = Run(
            code="RX-PC2-1",
            year=2026,
            sequence=1,
            reaction_id=rxn.id,
            status=STATUS_COMPLETED,
            completed_at=datetime(2026, 4, 1),
        )
        db.session.add(run)
        db.session.flush()
        db.session.add(
            RunComponent(
                run_id=run.id,
                substance_id=SM.id,
                role="starting_material",
                inventory_item_id=lot.id,
                actual_mass_g=12.0,
                position=0,
                is_limiting=True,
            )
        )
        # two product batches: 1 g of A, 3 g of B → total 4 g; cost 12 € → 3 €/g
        db.session.add_all(
            [
                InventoryItem(
                    substance_id=A.id,
                    batch_code="RX-PC2-1-P1",
                    initial_quantity_g=1.0,
                    is_active=True,
                    source_run_id=run.id,
                ),
                InventoryItem(
                    substance_id=B.id,
                    batch_code="RX-PC2-1-P2",
                    initial_quantity_g=3.0,
                    is_active=True,
                    source_run_id=run.id,
                ),
            ]
        )
        db.session.commit()

        report = compute_production_cost_report()
        a = next(s for s in report.substances if s.substance_name == "Prod-A")
        b = next(s for s in report.substances if s.substance_name == "Prod-B")
        # uniform €/g across the run's products; cost split by mass
        assert a.total_cost_cumulative == pytest.approx(3.0)  # 1 g × 3 €/g
        assert b.total_cost_cumulative == pytest.approx(9.0)  # 3 g × 3 €/g
        assert a.avg_per_g_cumulative == pytest.approx(3.0)
        assert b.avg_per_g_cumulative == pytest.approx(3.0)


def test_production_report_page_renders(app, client, admin_user):
    with app.app_context():
        _build_run_with_product()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_user)
        sess["_fresh"] = True

    resp = client.get("/reports/production")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Product-P" in body
    assert "RX-PC-1-P1" in body
