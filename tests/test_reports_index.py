"""Smoke tests for the reports index page.

The /reports/ landing displays cards linking to the three available
report views. We verify the three are reachable and rendered with
their titles. Doesn't test the report content itself — that's
covered by the per-view test modules.
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models import User


def _make_admin():
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


def _login(client):
    client.post(
        "/auth/login",
        data={"username": "r", "password": "x", "submit": "x"},
    )


def test_reports_index_shows_all_three_cards(app, client):
    """The landing must surface entries for spending, per-substance
    and per-template reports — all three should be reachable from
    this single page."""
    with app.app_context():
        _make_admin()

    _login(client)
    r = client.get("/reports/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)

    # Card titles (Italian source — locale defaults to 'it' for the admin)
    assert "Spese" in body
    assert "Sostanza" in body
    assert "Template di reazione" in body

    # Each card links to its target route
    assert "/reports/spending" in body
    assert "/reports/substance" in body
    assert "/runs/stats" in body


def test_reports_index_template_card_links_to_runs_stats(app, client):
    """Following the 'Template di reazione' link must land on a
    page that renders (smoke). Content is asserted elsewhere."""
    with app.app_context():
        _make_admin()

    _login(client)
    r = client.get("/runs/stats")
    assert r.status_code == 200
