"""Tests for the per-substance report service.

Builds a small dataset for one substance (EtOAc):
  - two lots at different prices/suppliers/dates (cost trend)
  - a completed run consuming some volume (consumption + coverage)
  - a run-step component consuming more
Then asserts each of the three views computes correctly.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    InventoryItem,
    Run,
    RunComponent,
    RunStep,
    RunStepComponent,
    Substance,
)
from stoic_eln.services.substance_report import (
    compute_substance_report,
    render_cost_sparkline_svg,
)


def _setup_etoac_dataset():
    """Create EtOAc with 2 lots, a completed run, a run-step consuming
    it. Returns the substance id. Inside app_context."""
    g = Group(name="L", slug="l", is_default=True, is_active=True)
    s = Substance(name="EtOAc", molecular_weight=88.11, density=0.902, is_solvent=True)
    db.session.add_all([g, s])
    db.session.commit()

    lot1 = InventoryItem(
        substance_id=s.id,
        group_id=g.id,
        batch_code="EA1",
        quantity_mL=500.0,
        initial_quantity_mL=1000.0,
        total_cost_eur=20.0,  # 0.020 €/mL
        purchased_at=date(2026, 1, 10),
        supplier="Sigma",
        is_active=True,
    )
    lot2 = InventoryItem(
        substance_id=s.id,
        group_id=g.id,
        batch_code="EA2",
        quantity_mL=2000.0,
        initial_quantity_mL=2000.0,
        total_cost_eur=35.0,  # 0.0175 €/mL
        purchased_at=date(2026, 3, 15),
        supplier="TCI",
        is_active=True,
    )
    db.session.add_all([lot1, lot2])
    db.session.commit()

    # A completed run consuming 250 mL (via main component)
    run = Run(
        code="R-001",
        sequence=1,
        year=2026,
        reaction_id=0,
        status="completed",
        completed_at=datetime(2026, 2, 1, 12, 0),
    )
    db.session.add(run)
    db.session.commit()
    rc = RunComponent(run_id=run.id, substance_id=s.id, role="reactant", actual_volume_mL=250.0)
    db.session.add(rc)
    db.session.commit()

    # A run-step consuming another 50 mL
    step = RunStep(run_id=run.id, title="wash", kind="workup", position=1)
    db.session.add(step)
    db.session.commit()
    sc = RunStepComponent(
        step_id=step.id, substance_id=s.id, role="reactant", actual_volume_mL=50.0
    )
    db.session.add(sc)
    db.session.commit()

    return s.id


# ── Consumption view ────────────────────────────────────────────────


def test_consumption_sums_runs_and_steps(app):
    with app.app_context():
        sid = _setup_etoac_dataset()
        report = compute_substance_report(sid, date_from=date(2026, 1, 1), date_to=date(2026, 5, 1))
        assert report is not None
        # 250 mL from run + 50 mL from step = 300 mL
        assert report.consumption.total_mL == pytest.approx(300.0)
        assert report.consumption.total_g == pytest.approx(0.0)

        by_source = {b.source: b for b in report.consumption.by_source}
        assert by_source["runs"].total_mL == pytest.approx(250.0)
        assert by_source["runs"].event_count == 1
        assert by_source["run_steps"].total_mL == pytest.approx(50.0)
        assert by_source["run_steps"].event_count == 1
        assert by_source["preps"].total_mL == pytest.approx(0.0)


def test_consumption_excludes_runs_outside_window(app):
    with app.app_context():
        sid = _setup_etoac_dataset()
        # Window starts AFTER the run's completion date
        report = compute_substance_report(sid, date_from=date(2026, 3, 1), date_to=date(2026, 5, 1))
        # The run completed 2026-02-01, outside the window → no consumption
        assert report.consumption.total_mL == pytest.approx(0.0)


def test_consumption_excludes_non_completed_runs(app):
    with app.app_context():
        g = Group(name="L", slug="l")
        s = Substance(name="DCM", molecular_weight=84.93)
        db.session.add_all([g, s])
        db.session.commit()
        # An in_progress run — must NOT count
        run = Run(
            code="R-002",
            sequence=2,
            year=2026,
            reaction_id=0,
            status="in_progress",
            started_at=datetime(2026, 2, 1, 9, 0),
        )
        db.session.add(run)
        db.session.commit()
        rc = RunComponent(run_id=run.id, substance_id=s.id, role="reactant", actual_volume_mL=100.0)
        db.session.add(rc)
        db.session.commit()

        report = compute_substance_report(
            s.id, date_from=date(2026, 1, 1), date_to=date(2026, 5, 1)
        )
        assert report.consumption.total_mL == pytest.approx(0.0)


# ── Coverage view ───────────────────────────────────────────────────


def test_coverage_computes_daily_rate_and_stock(app):
    with app.app_context():
        sid = _setup_etoac_dataset()
        date_from = date(2026, 1, 1)
        date_to = date(2026, 5, 1)
        report = compute_substance_report(sid, date_from=date_from, date_to=date_to)

        period_days = (date_to - date_from).days  # 120
        # 300 mL consumed over 120 days = 2.5 mL/day
        assert report.coverage.daily_mL == pytest.approx(300.0 / period_days)
        # Current stock: 500 + 2000 = 2500 mL
        assert report.coverage.stock_mL == pytest.approx(2500.0)
        # Coverage: 2500 / (300/120) = 1000 days
        assert report.coverage.coverage_days_mL == pytest.approx(2500.0 / (300.0 / period_days))
        assert report.coverage.enough_data is True


def test_coverage_no_consumption_means_not_enough_data(app):
    with app.app_context():
        g = Group(name="L", slug="l")
        s = Substance(name="Toluene", molecular_weight=92.14)
        db.session.add_all([g, s])
        db.session.commit()
        # Stock but no consumption
        lot = InventoryItem(
            substance_id=s.id,
            group_id=g.id,
            batch_code="T1",
            quantity_mL=1000.0,
            initial_quantity_mL=1000.0,
            purchased_at=date(2026, 1, 1),
            is_active=True,
        )
        db.session.add(lot)
        db.session.commit()

        report = compute_substance_report(
            s.id, date_from=date(2026, 1, 1), date_to=date(2026, 5, 1)
        )
        assert report.coverage.daily_mL is None
        assert report.coverage.coverage_days_mL is None
        assert report.coverage.enough_data is False


# ── Cost trend view ─────────────────────────────────────────────────


def test_cost_trend_points_and_suppliers(app):
    with app.app_context():
        sid = _setup_etoac_dataset()
        report = compute_substance_report(sid, date_from=date(2026, 1, 1), date_to=date(2026, 5, 1))
        ct = report.cost_trend
        assert ct.has_data is True
        # 2 lots → 2 points, sorted by purchase date ascending
        assert len(ct.points) == 2
        assert ct.points[0].supplier == "Sigma"  # Jan
        assert ct.points[1].supplier == "TCI"  # Mar
        # Unit price: Sigma 20/1000 = 0.02, TCI 35/2000 = 0.0175
        assert ct.points[0].unit_price == pytest.approx(0.020)
        assert ct.points[1].unit_price == pytest.approx(0.0175)

        # Two suppliers, sorted alphabetically
        by_sup = {c.supplier: c for c in ct.by_supplier}
        assert by_sup["Sigma"].avg_price == pytest.approx(0.020)
        assert by_sup["TCI"].avg_price == pytest.approx(0.0175)
        assert by_sup["Sigma"].lot_count == 1


def test_cost_trend_excludes_lots_outside_window(app):
    with app.app_context():
        sid = _setup_etoac_dataset()
        # Window covers only Jan-Feb → only the Sigma lot
        report = compute_substance_report(
            sid, date_from=date(2026, 1, 1), date_to=date(2026, 2, 28)
        )
        ct = report.cost_trend
        assert len(ct.points) == 1
        assert ct.points[0].supplier == "Sigma"


# ── SVG rendering ───────────────────────────────────────────────────


def test_cost_sparkline_renders_with_two_points(app):
    with app.app_context():
        sid = _setup_etoac_dataset()
        report = compute_substance_report(sid, date_from=date(2026, 1, 1), date_to=date(2026, 5, 1))
        svg = render_cost_sparkline_svg(report.cost_trend.points)
        assert svg.startswith("<svg")
        assert "polyline" in svg or "path" in svg


def test_cost_sparkline_empty_with_one_point(app):
    with app.app_context():
        sid = _setup_etoac_dataset()
        report = compute_substance_report(
            sid, date_from=date(2026, 1, 1), date_to=date(2026, 2, 28)
        )
        # Only one priced point → no sparkline
        svg = render_cost_sparkline_svg(report.cost_trend.points)
        assert svg == ""


# ── Missing substance ───────────────────────────────────────────────


def test_report_none_for_missing_substance(app):
    with app.app_context():
        report = compute_substance_report(
            99999, date_from=date(2026, 1, 1), date_to=date(2026, 5, 1)
        )
        assert report is None


# ── Route smoke tests ───────────────────────────────────────────────


def _login(client):
    client.post("/auth/login", data={"username": "r", "password": "x", "submit": "x"})


def _make_admin():
    from stoic_eln.models import User

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
    db.session.commit()


def test_route_substance_picker_renders_without_id(app, client):
    """GET /reports/substance with no id renders the picker page."""
    with app.app_context():
        _make_admin()
        _setup_etoac_dataset()

    _login(client)
    r = client.get("/reports/substance")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "EtOAc" in body  # appears in the picker dropdown


def test_route_substance_report_renders_with_id(app, client):
    """GET /reports/substance/<id> renders the full report."""
    with app.app_context():
        _make_admin()
        sid = _setup_etoac_dataset()

    _login(client)
    r = client.get(f"/reports/substance/{sid}?period=12m")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # All three view headers present
    assert "Consumo" in body
    assert "Copertura" in body
    assert "prezzi" in body.lower()
    # Suppliers from the dataset
    assert "Sigma" in body
    assert "TCI" in body


def test_route_substance_report_unknown_id_shows_warning(app, client):
    with app.app_context():
        _make_admin()

    _login(client)
    r = client.get("/reports/substance/99999")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "non trovata" in body.lower()
