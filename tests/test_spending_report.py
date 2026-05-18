"""Tests for the spending report service (patch 14.6.8)."""

from __future__ import annotations

from datetime import date

from stoic_eln.extensions import db
from stoic_eln.models import Group, Substance
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.services.spending_report import (
    SpendingReport,
    compute_spending,
)


def _make_lot(*, purchased_at, cost, name="Test sub", group=None):
    """Helper: create a substance + inventory lot in one call."""
    sub = Substance(name=name)
    db.session.add(sub); db.session.flush()
    if group is None:
        group = Group(name="L", slug="l")
        db.session.add(group); db.session.flush()
    lot = InventoryItem(
        substance_id=sub.id, group_id=group.id,
        batch_code=f"{name}-001",
        quantity_g=100.0, initial_quantity_g=100.0,
        purchased_at=purchased_at,
        total_cost_eur=cost,
        is_active=True,
    )
    db.session.add(lot); db.session.flush()
    return lot


# ── Basic bucketing ────────────────────────────────────────────────


def test_compute_spending_month_bucket_sums_within_month(app):
    """Two purchases in the same month → one bucket with sum."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        _make_lot(purchased_at=date(2026, 3, 5), cost=100.0,
                  name="A", group=g)
        _make_lot(purchased_at=date(2026, 3, 20), cost=50.0,
                  name="B", group=g)
        db.session.commit()

        report = compute_spending(bucket="month")
        assert len(report.rows) == 1
        assert report.rows[0].total_eur == 150.0
        assert report.rows[0].purchase_count == 2
        assert report.grand_total_eur == 150.0


def test_compute_spending_separates_different_months(app):
    """Purchases in March and April → two distinct buckets."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        _make_lot(purchased_at=date(2026, 3, 5), cost=100.0,
                  name="A", group=g)
        _make_lot(purchased_at=date(2026, 4, 5), cost=200.0,
                  name="B", group=g)
        db.session.commit()

        report = compute_spending(bucket="month")
        assert len(report.rows) == 2
        # Newest first (2026-04 before 2026-03)
        assert report.rows[0].total_eur == 200.0
        assert report.rows[1].total_eur == 100.0


def test_compute_spending_quarter_bucket(app):
    """Quarter bucket: Jan + Feb + Mar all go into Q1."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        _make_lot(purchased_at=date(2026, 1, 15), cost=10.0,
                  name="A", group=g)
        _make_lot(purchased_at=date(2026, 2, 15), cost=20.0,
                  name="B", group=g)
        _make_lot(purchased_at=date(2026, 3, 15), cost=30.0,
                  name="C", group=g)
        db.session.commit()

        report = compute_spending(bucket="quarter")
        assert len(report.rows) == 1
        assert report.rows[0].total_eur == 60.0
        assert report.rows[0].key == "2026-Q1"


def test_compute_spending_year_bucket(app):
    """Year bucket: lots from 2026 grouped into one row."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        _make_lot(purchased_at=date(2026, 1, 15), cost=10.0,
                  name="A", group=g)
        _make_lot(purchased_at=date(2026, 11, 15), cost=20.0,
                  name="B", group=g)
        _make_lot(purchased_at=date(2025, 7, 15), cost=100.0,
                  name="C", group=g)
        db.session.commit()

        report = compute_spending(bucket="year")
        assert len(report.rows) == 2
        # Newest first
        assert report.rows[0].key == "2026"
        assert report.rows[0].total_eur == 30.0
        assert report.rows[1].key == "2025"
        assert report.rows[1].total_eur == 100.0


def test_compute_spending_week_bucket(app):
    """Week bucket: ISO week, Monday-anchored."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        # Both dates fall in ISO week 2026-W21
        _make_lot(purchased_at=date(2026, 5, 18), cost=10.0,
                  name="A", group=g)  # Monday
        _make_lot(purchased_at=date(2026, 5, 24), cost=20.0,
                  name="B", group=g)  # Sunday
        # This one is in W22
        _make_lot(purchased_at=date(2026, 5, 25), cost=100.0,
                  name="C", group=g)  # Next Monday
        db.session.commit()

        report = compute_spending(bucket="week")
        assert len(report.rows) == 2
        assert report.rows[0].key == "2026-W22"  # newest first
        assert report.rows[0].total_eur == 100.0
        assert report.rows[1].key == "2026-W21"
        assert report.rows[1].total_eur == 30.0


# ── Filters ────────────────────────────────────────────────────────


def test_compute_spending_respects_date_from_filter(app):
    """date_from filter excludes earlier lots."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        _make_lot(purchased_at=date(2026, 1, 15), cost=100.0,
                  name="A", group=g)
        _make_lot(purchased_at=date(2026, 3, 15), cost=200.0,
                  name="B", group=g)
        db.session.commit()

        report = compute_spending(bucket="month", date_from=date(2026, 2, 1))
        assert report.grand_total_eur == 200.0
        assert len(report.rows) == 1


def test_compute_spending_respects_date_to_filter(app):
    """date_to filter excludes later lots."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        _make_lot(purchased_at=date(2026, 1, 15), cost=100.0,
                  name="A", group=g)
        _make_lot(purchased_at=date(2026, 6, 15), cost=200.0,
                  name="B", group=g)
        db.session.commit()

        report = compute_spending(bucket="month", date_to=date(2026, 4, 1))
        assert report.grand_total_eur == 100.0


# ── Edge cases ─────────────────────────────────────────────────────


def test_compute_spending_skips_lots_without_purchased_at(app):
    """A lot without purchased_at can't be bucketed and is silently
    skipped — won't show in the report nor in the missing_cost count."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        sub = Substance(name="No-date")
        db.session.add(sub); db.session.flush()
        lot = InventoryItem(
            substance_id=sub.id, group_id=g.id,
            batch_code="X-001",
            quantity_g=10.0, initial_quantity_g=10.0,
            purchased_at=None,
            total_cost_eur=50.0,
            is_active=True,
        )
        db.session.add(lot); db.session.commit()

        report = compute_spending(bucket="month")
        assert report.grand_total_eur == 0.0
        assert report.grand_purchase_count == 0


def test_compute_spending_counts_lots_with_missing_cost(app):
    """A lot with purchased_at set but no cost gets surfaced as
    'missing_cost_count' so the user knows the report is partial."""
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        sub = Substance(name="No-cost")
        db.session.add(sub); db.session.flush()
        lot = InventoryItem(
            substance_id=sub.id, group_id=g.id,
            batch_code="X-001",
            quantity_g=10.0, initial_quantity_g=10.0,
            purchased_at=date(2026, 3, 15),
            total_cost_eur=None,  # missing!
            is_active=True,
        )
        db.session.add(lot); db.session.commit()

        report = compute_spending(bucket="month")
        # Counted as a purchase but not added to total
        assert report.grand_total_eur == 0.0
        assert report.grand_purchase_count == 1
        assert report.missing_cost_count == 1


def test_compute_spending_empty_returns_empty_report(app):
    """No data → empty rows, zero totals, no crash."""
    with app.app_context():
        report = compute_spending(bucket="month")
        assert isinstance(report, SpendingReport)
        assert report.rows == []
        assert report.grand_total_eur == 0.0


def test_compute_spending_rejects_unknown_bucket(app):
    """Invalid bucket name → ValueError (defensive)."""
    import pytest
    with app.app_context():
        with pytest.raises(ValueError):
            compute_spending(bucket="decade")


# ── HTTP routes ────────────────────────────────────────────────────


def _login_user(client, app):
    """Helper: create a minimal user and log in via session."""
    from stoic_eln.models import User
    with app.app_context():
        u = User(
            email="u@lab.it", username="u", full_name="U",
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$"
                          "AAAAAAAAAAAAAAAAAAAAAA$" + "x" * 43,
            role="supervisor",
        )
        db.session.add(u); db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True


def test_reports_index_renders(app, client):
    _login_user(client, app)
    resp = client.get("/reports/")
    assert resp.status_code == 200
    assert b"Spese" in resp.data or b"Spending" in resp.data


def test_spending_page_renders_with_data(app, client):
    _login_user(client, app)
    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        _make_lot(purchased_at=date(2026, 3, 5), cost=100.0,
                  name="A", group=g)
        db.session.commit()
    resp = client.get("/reports/spending?bucket=month")
    assert resp.status_code == 200
    # Look for the formatted total
    assert b"100" in resp.data


def test_spending_page_accepts_date_range_filter(app, client):
    _login_user(client, app)
    resp = client.get(
        "/reports/spending?bucket=month&from=2026-01-01&to=2026-12-31"
    )
    assert resp.status_code == 200


def test_spending_page_unknown_bucket_falls_back_to_month(app, client):
    """An invalid bucket from the URL shouldn't 500 — defaults to month."""
    _login_user(client, app)
    resp = client.get("/reports/spending?bucket=garbage")
    assert resp.status_code == 200
