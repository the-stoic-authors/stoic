"""Tests for the bench-mode UX patch.

The actual bench-mode switch lives client-side (JS toggles a body
class). We can't exercise that here, but we can verify:

- The CSS and JS assets exist and are served by the static handler
- The base.html links them in the page head and body
- The run detail page exposes a [data-bench-toggle] button only for
  running runs (not for draft or completed ones)
- Numeric inputs declare inputmode="decimal" so phones/tablets pop
  up a number keypad
"""

from __future__ import annotations

from datetime import datetime

from stoic_eln.extensions import db
from stoic_eln.models import Run, User


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
    return u


def _login(client):
    client.post(
        "/auth/login",
        data={"username": "r", "password": "x", "submit": "x"},
    )


def _build_minimal_run(status: str) -> int:
    """Build the smallest Run row that can render in detail.html.

    The Run requires sequence + year + status; reaction_id can be
    0 since the template guards against ``run.reaction`` being None.
    Mirrors the pattern in tests/test_run_setup.py for product lot
    bootstrap.
    """
    started = datetime(2026, 6, 1, 10, 0) if status != "draft" else None
    completed = datetime(2026, 6, 1, 12, 0) if status == "completed" else None
    run = Run(
        code=f"RX-BENCH-{status[:3].upper()}",
        sequence=1,
        year=2026,
        reaction_id=0,
        status=status,
        started_at=started,
        completed_at=completed,
    )
    db.session.add(run)
    db.session.commit()
    return run.id


# ── Static assets ──────────────────────────────────────────────────


def test_bench_css_is_served(app, client):
    r = client.get("/static/css/bench.css")
    assert r.status_code == 200
    assert r.mimetype == "text/css"
    body = r.get_data(as_text=True)
    # Spot-check a few key declarations to catch silent truncation
    assert ".bench-mode" in body
    assert ".bench-topbar" in body


def test_bench_js_is_served(app, client):
    r = client.get("/static/js/bench.js")
    assert r.status_code == 200
    assert "javascript" in r.mimetype
    body = r.get_data(as_text=True)
    assert "data-bench-toggle" in body
    assert "bench-mode" in body
    assert "sessionStorage" in body


# ── base.html wiring ───────────────────────────────────────────────


def test_base_template_loads_bench_css_and_js(app, client):
    with app.app_context():
        _make_admin()
    _login(client)

    r = client.get("/dashboard")
    body = r.get_data(as_text=True)
    assert "css/bench.css" in body
    assert "js/bench.js" in body
    # The localised exit label is exposed to the JS via a global
    assert "STOIC_BENCH_EXIT_LABEL" in body


# ── Detail page toggle ─────────────────────────────────────────────


def test_running_run_shows_bench_toggle(app, client):
    """A run in 'in_progress' status must surface the Bench toggle
    button so the operator can switch into kiosk view at the bench."""
    with app.app_context():
        _make_admin()
        run_id = _build_minimal_run("in_progress")
    _login(client)

    r = client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "data-bench-toggle" in body
    assert f'data-run-id="{run_id}"' in body
    assert "RX-BENCH-IN_" in body or "RX-BENCH" in body


def test_draft_run_does_not_show_bench_toggle(app, client):
    """In setup mode the bench toggle would be misleading — the
    operator is still configuring lots, not executing."""
    with app.app_context():
        _make_admin()
        run_id = _build_minimal_run("draft")
    _login(client)

    r = client.get(f"/runs/{run_id}")
    body = r.get_data(as_text=True)
    assert "data-bench-toggle" not in body


def test_completed_run_does_not_show_bench_toggle(app, client):
    """A finished run is a record, not a workflow — no kiosk view."""
    with app.app_context():
        _make_admin()
        run_id = _build_minimal_run("completed")
    _login(client)

    r = client.get(f"/runs/{run_id}")
    body = r.get_data(as_text=True)
    assert "data-bench-toggle" not in body


# ── Mobile-friendly numeric inputs ─────────────────────────────────


def test_run_detail_numeric_inputs_have_inputmode_decimal(app, client):
    """All ``type="number"`` inputs on the run detail page must
    declare ``inputmode="decimal"`` so iOS/Android pop up the numeric
    keypad instead of the full QWERTY one. The bench operator has
    one hand on the balance — saving them a keyboard switch matters."""
    with app.app_context():
        _make_admin()
        run_id = _build_minimal_run("in_progress")
    _login(client)

    r = client.get(f"/runs/{run_id}")
    body = r.get_data(as_text=True)

    n_number = body.count('type="number"')
    n_decimal = body.count('inputmode="decimal"')
    assert n_number > 0, "expected some numeric inputs on the page"
    assert n_decimal >= n_number, (
        f"only {n_decimal} of {n_number} number inputs declare inputmode=decimal"
    )
