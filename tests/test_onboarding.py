"""Tests for the onboarding wizard."""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models import User
from stoic_eln.models.settings import AppSetting


def _make_admin(username="admin", password="x"):
    u = User(
        username=username,
        full_name="Admin",
        operator_code="AA",
        role="admin",
        is_admin=True,
        is_active=True,
        locale="it",
    )
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def _make_operator(username="op", password="x"):
    u = User(
        username=username,
        full_name="Operator",
        operator_code="OP",
        role="operator",
        is_admin=False,
        is_active=True,
        locale="it",
    )
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, username, password="x"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password, "submit": "x"},
    )


def _clear_completion_flag():
    """Tests that simulate the first-run state remove the
    'completed' flag that the conftest pre-populates for the rest
    of the suite."""
    item = db.session.get(AppSetting, "onboarding.completed_at")
    if item is not None:
        db.session.delete(item)
        db.session.commit()


# ── Initial state: redirects an admin to /onboarding ────────────────


def test_admin_redirected_to_onboarding_when_not_completed(app, client):
    with app.app_context():
        _clear_completion_flag()
        _make_admin()
    _login(client, "admin")

    r = client.get("/", follow_redirects=False)
    # Should redirect to onboarding index
    assert r.status_code in (302, 303)
    assert "/onboarding" in r.location


def test_non_admin_not_redirected_to_onboarding(app, client):
    """Operators (non-admin) must NOT see the wizard — they don't
    have permission to change global settings anyway."""
    with app.app_context():
        _clear_completion_flag()
        _make_operator()
    _login(client, "op")

    r = client.get("/", follow_redirects=False)
    # No redirect to /onboarding
    if r.status_code in (302, 303):
        assert "/onboarding" not in (r.location or "")


def test_completed_admin_not_redirected(app, client):
    """Once the wizard has been completed, admins go straight to
    their requested page."""
    with app.app_context():
        _make_admin()
        AppSetting.set("onboarding.completed_at", "2026-01-01T00:00:00")
    _login(client, "admin")

    r = client.get("/", follow_redirects=False)
    # Either renders directly (200) or redirects somewhere OTHER than
    # /onboarding (e.g. to /dashboard depending on main.index behaviour)
    if r.status_code in (302, 303):
        assert "/onboarding" not in (r.location or "")


# ── Step navigation ─────────────────────────────────────────────────


def test_welcome_page_renders(app, client):
    with app.app_context():
        _make_admin()
    _login(client, "admin")

    r = client.get("/onboarding/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Benvenuto" in body or "Welcome" in body
    assert "Inizia" in body or "Start" in body


def test_lab_step_saves_name(app, client):
    with app.app_context():
        _make_admin()
    _login(client, "admin")

    r = client.post(
        "/onboarding/lab",
        data={"lab_name": "Lab Test"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "/onboarding/currency" in r.location

    with app.app_context():
        assert AppSetting.get("lab.name") == "Lab Test"


def test_lab_step_rejects_empty_name(app, client):
    with app.app_context():
        _make_admin()
    _login(client, "admin")

    r = client.post(
        "/onboarding/lab",
        data={"lab_name": "  "},
        follow_redirects=False,
    )
    # Re-renders the form (200), no redirect
    assert r.status_code == 200

    with app.app_context():
        assert AppSetting.get("lab.name") is None


def test_currency_step_saves_code(app, client):
    with app.app_context():
        _make_admin()
    _login(client, "admin")

    r = client.post(
        "/onboarding/currency",
        data={"currency": "USD"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "/onboarding/run-code" in r.location

    with app.app_context():
        from stoic_eln.services.currency import get_currency_code

        assert get_currency_code() == "USD"


def test_currency_step_rejects_invalid_code(app, client):
    with app.app_context():
        _make_admin()
    _login(client, "admin")

    r = client.post(
        "/onboarding/currency",
        data={"currency": "INVALID"},
        follow_redirects=False,
    )
    # Re-renders (200), no save
    assert r.status_code == 200


def test_run_code_step_applies_preset(app, client):
    with app.app_context():
        _make_admin()
    _login(client, "admin")

    # Pick preset 1 (year + 4-digit sequence)
    r = client.post(
        "/onboarding/run-code",
        data={"preset": "1"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert "/onboarding/done" in r.location

    with app.app_context():
        from stoic_eln.services.run_code import get_format

        assert "{year}" in get_format()
        assert "{seq:04d}" in get_format()


def test_done_step_marks_completed(app, client):
    with app.app_context():
        _clear_completion_flag()
        _make_admin()
    _login(client, "admin")

    # Pre-populate everything so the summary shows real values
    with app.app_context():
        AppSetting.set("lab.name", "Test Lab")

    # GET shows the summary
    r = client.get("/onboarding/done")
    assert r.status_code == 200
    assert "Test Lab" in r.get_data(as_text=True)

    # POST marks completion and redirects
    r = client.post("/onboarding/done", follow_redirects=False)
    assert r.status_code in (302, 303)

    with app.app_context():
        assert AppSetting.get("onboarding.completed_at") is not None

    # Subsequent dashboard request must NOT redirect to /onboarding
    r = client.get("/", follow_redirects=False)
    if r.status_code in (302, 303):
        assert "/onboarding" not in (r.location or "")


def test_skip_does_not_mark_completed(app, client):
    with app.app_context():
        _clear_completion_flag()
        _make_admin()
    _login(client, "admin")

    r = client.get("/onboarding/skip", follow_redirects=False)
    assert r.status_code in (302, 303)

    with app.app_context():
        # Still not completed → wizard would still appear at next login
        assert AppSetting.get("onboarding.completed_at") is None


# ── Lab name shows in templates ─────────────────────────────────────


def test_lab_name_from_appsetting_appears_in_base_template(app, client):
    """When the wizard has saved a lab name, the base template
    reflects it (overrides the config default)."""
    with app.app_context():
        _make_admin()
        AppSetting.set("lab.name", "Lab della Patch")
        AppSetting.set("onboarding.completed_at", "2026-01-01T00:00:00")
    _login(client, "admin")

    r = client.get("/", follow_redirects=True)
    assert r.status_code == 200
    assert "Lab della Patch" in r.get_data(as_text=True)


# ── CSRF protection ────────────────────────────────────────────────


def test_all_wizard_forms_include_csrf_token(app, client):
    """Every POST endpoint of the wizard renders a form that
    includes a CSRF token. Without it, real-browser submissions
    are rejected by Flask-WTF (the test client bypasses CSRF
    under TESTING, so this assertion is the only check.)
    """
    with app.app_context():
        _clear_completion_flag()
        _make_admin()
    _login(client, "admin")

    for path in (
        "/onboarding/lab",
        "/onboarding/currency",
        "/onboarding/run-code",
        "/onboarding/done",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        body = r.get_data(as_text=True)
        assert 'name="csrf_token"' in body, f"{path} missing csrf_token field"
