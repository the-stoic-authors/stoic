"""Tests for user roles and role-based access control."""

from __future__ import annotations

import re


from stoic_eln.extensions import db
from stoic_eln.models.user import User
from stoic_eln.models.reaction import Reaction


def _create_user(app, *, username="alice", role="user", is_admin=False):
    with app.app_context():
        u = User(
            username=username,
            full_name=username.capitalize(),
            operator_code=username[:2].upper(),
            role=role,
            is_admin=is_admin,
            is_active=True,
            locale="it",
        )
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        return u.id


def _login(client, username):
    r = client.get("/auth/login")
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', r.data)
    csrf = m.group(1).decode() if m else None
    return client.post("/auth/login", data={
        "csrf_token": csrf,
        "username": username,
        "password": "password123",
        "submit": "x",
    }, follow_redirects=False)


# ─── Model property tests ───────────────────────────────────────────────────


def test_role_default_is_user(app):
    with app.app_context():
        u = User(username="x", full_name="X", role="user", is_admin=False)
        assert u.role == "user"
        assert not u.is_supervisor
        assert not u.can_edit_reactions
        assert not u.can_manage_admin


def test_supervisor_can_edit_but_not_manage_admin(app):
    with app.app_context():
        u = User(username="x", full_name="X", role="supervisor", is_admin=False)
        assert u.is_supervisor
        assert u.can_edit_reactions
        assert not u.can_manage_admin


def test_admin_role_implies_supervisor(app):
    with app.app_context():
        u = User(username="x", full_name="X", role="admin", is_admin=True)
        assert u.is_supervisor
        assert u.can_edit_reactions
        assert u.can_manage_admin


def test_legacy_is_admin_flag_is_treated_as_admin(app):
    """Existing pre-role admins (is_admin=True, role='user') still behave as admin."""
    with app.app_context():
        u = User(username="x", full_name="X", role="user", is_admin=True)
        # Through the helpers, is_admin still grants access.
        assert u.is_supervisor
        assert u.can_edit_reactions
        assert u.can_manage_admin


def test_sync_role_flags_promotes_legacy_admin(app):
    """sync_role_flags() upgrades legacy is_admin=True users to role='admin'."""
    with app.app_context():
        u = User(username="x", full_name="X", role="user", is_admin=True)
        u.sync_role_flags()
        assert u.role == "admin"


# ─── Route access tests ─────────────────────────────────────────────────────


def test_user_cannot_create_reaction(app, client):
    """A regular user gets 403 when trying to create a reaction."""
    _create_user(app, username="bob", role="user", is_admin=False)
    _login(client, "bob")
    resp = client.post("/reactions/new", follow_redirects=False)
    assert resp.status_code == 403


def test_supervisor_can_create_reaction(app, client):
    _create_user(app, username="sue", role="supervisor", is_admin=False)
    _login(client, "sue")
    resp = client.post("/reactions/new", follow_redirects=False)
    assert resp.status_code in (200, 302)


def test_user_cannot_change_user_role(app, client):
    """Only admins can change roles via /settings/users."""
    _create_user(app, username="bob", role="user", is_admin=False)
    target_id = _create_user(app, username="alice", role="user", is_admin=False)
    _login(client, "bob")
    resp = client.post(f"/settings/users/{target_id}/role",
                       data={"role": "admin"})
    assert resp.status_code == 403


def test_supervisor_cannot_change_user_role(app, client):
    """Even supervisors cannot grant admin (only admins can)."""
    _create_user(app, username="sue", role="supervisor", is_admin=False)
    target_id = _create_user(app, username="alice", role="user", is_admin=False)
    _login(client, "sue")
    resp = client.post(f"/settings/users/{target_id}/role",
                       data={"role": "admin"})
    assert resp.status_code == 403


def test_admin_can_change_user_role(app, client):
    _create_user(app, username="root", role="admin", is_admin=True)
    target_id = _create_user(app, username="alice", role="user", is_admin=False)
    _login(client, "root")
    resp = client.post(f"/settings/users/{target_id}/role",
                       data={"role": "supervisor"},
                       follow_redirects=False)
    assert resp.status_code in (200, 302)
    with app.app_context():
        u = db.session.get(User, target_id)
        assert u.role == "supervisor"


def test_cannot_demote_last_admin(app, client):
    """Block demoting the only admin to prevent lockout."""
    admin_id = _create_user(app, username="root", role="admin", is_admin=True)
    _login(client, "root")
    # Try to demote self via a different account is needed; here we have
    # only one admin → demoting them fails.
    # Login as root, try to demote some other admin? We only have root.
    # So we POST to demote root (the only admin) — should be blocked.
    resp = client.post(f"/settings/users/{admin_id}/role",
                       data={"role": "user"},
                       follow_redirects=False)
    assert resp.status_code in (200, 302)
    with app.app_context():
        u = db.session.get(User, admin_id)
        assert u.role == "admin", "Last admin should not have been demoted"


def test_run_placeholder_accessible_to_all(app, client):
    """Even a regular user can hit the Esegui run placeholder."""
    _create_user(app, username="bob", role="user", is_admin=False)
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test", status="published")
        db.session.add(rxn); db.session.commit()
        rid = rxn.id
    _login(client, "bob")
    resp = client.get(f"/reactions/{rid}/run")
    assert resp.status_code == 200
    assert b"Settimana 4" in resp.data or b"In arrivo" in resp.data


# ─── View-mode HTML rendering tests ─────────────────────────────────────────


def test_published_reaction_renders_in_view_mode(app, client):
    """A published reaction page should NOT contain editable inputs/forms."""
    _create_user(app, username="root", role="admin", is_admin=True)
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", status="published",
                       title="Test", template_code="TEST")
        db.session.add(rxn); db.session.commit()
        rid = rxn.id
    _login(client, "root")
    resp = client.get(f"/reactions/{rid}")
    assert resp.status_code == 200
    html = resp.data.decode()

    # View-mode should NOT have:
    forbidden = [
        "/components/",                  # × on components (any /components/N/delete URL)
        "Imposta come limitante",        # ★ button
        "/checklist/new",                # +Add for checklist
        "/checklist/",                   # any toggle/edit/move/delete
        "readonly",                      # readonly inputs
        "Stai modificando una bozza",    # draft banner
    ]
    for needle in forbidden:
        assert needle not in html, f"View-mode HTML should not contain {needle!r}"

    # View-mode SHOULD have:
    expected = [
        "Visualizzazione: solo lettura",  # banner
        "Esegui run",                     # action button
    ]
    for needle in expected:
        assert needle in html, f"View-mode HTML should contain {needle!r}"


def test_draft_reaction_renders_in_edit_mode(app, client):
    """A draft reaction page should have editable inputs and action buttons."""
    _create_user(app, username="root", role="admin", is_admin=True)
    with app.app_context():
        rxn = Reaction(code="RX-DRAFT-1", status="draft",
                       title="Draft test")
        db.session.add(rxn); db.session.commit()
        rid = rxn.id
    _login(client, "root")
    resp = client.get(f"/reactions/{rid}")
    assert resp.status_code == 200
    html = resp.data.decode()

    expected = [
        "Stai modificando una bozza",   # draft banner
        "/checklist/new",                # +Add form action url
        "Salva",                         # save button
        "Aggiungi una voce",             # placeholder for add input
    ]
    for needle in expected:
        assert needle in html, f"Edit-mode HTML should contain {needle!r}"

    # The view-mode banner should NOT show on a draft
    assert "Visualizzazione: solo lettura" not in html
