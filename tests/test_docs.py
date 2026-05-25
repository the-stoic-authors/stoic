"""Tests for the in-app documentation blueprint (Settimana 6 patch 14.6).

Covers:
* Index page lists user manual for everyone, admin/dev only for admins
* Per-manual routes return 200 for the right role, 403 for the wrong one
* Language toggle (?lang=it|en) flips the rendered content
* Missing slugs return 404
* Markdown is actually rendered (HTML in the body, not raw markdown)
"""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import User


@pytest.fixture
def regular_user(app):
    """A non-admin user, logged-in client returned by ``client_user``."""
    with app.app_context():
        u = User(
            username="alice",
            full_name="Alice User",
            operator_code="ALI",
            role="user",
            is_admin=False,
            is_active=True,
            locale="it",
        )
        u.set_password("test12345")
        db.session.add(u)
        db.session.commit()
    return u


@pytest.fixture
def client_user(client, regular_user):
    """Test client logged in as a regular (non-admin) user."""
    client.post(
        "/auth/login",
        data={
            "username": "alice",
            "password": "test12345",
            "submit": "x",
        },
    )
    return client


@pytest.fixture
def client_admin(client, admin_user):
    """Test client logged in as the default admin."""
    client.post(
        "/auth/login",
        data={
            "username": "testadmin",
            "password": "testpassword123",
            "submit": "x",
        },
    )
    return client


# ── Index ────────────────────────────────────────────────────────


def test_docs_index_visible_to_users(client_user):
    """Any logged-in user sees the docs landing page."""
    r = client_user.get("/docs/")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Manuale utente" in body
    # Admin-only manuals must NOT appear for regular users
    assert "Manuale amministratore" not in body
    assert "Manuale sviluppatore" not in body


def test_docs_index_shows_all_manuals_to_admin(client_admin):
    """Admins see user, admin, and developer manuals."""
    r = client_admin.get("/docs/")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Manuale utente" in body
    assert "Manuale amministratore" in body
    assert "Manuale sviluppatore" in body


def test_docs_index_requires_login(client):
    """Anonymous users redirected to login."""
    r = client.get("/docs/", follow_redirects=False)
    assert r.status_code in (301, 302)


# ── Per-manual access control ────────────────────────────────────


def test_user_manual_accessible_to_regular_user(client_user):
    r = client_user.get("/docs/user")
    assert r.status_code == 200
    # Confirm markdown actually rendered to HTML
    assert b"<h1" in r.data
    assert b"<h2" in r.data


def test_admin_manual_forbidden_for_regular_user(client_user):
    r = client_user.get("/docs/admin")
    assert r.status_code == 403


def test_developer_manual_forbidden_for_regular_user(client_user):
    r = client_user.get("/docs/developer")
    assert r.status_code == 403


def test_admin_manual_accessible_to_admin(client_admin):
    r = client_admin.get("/docs/admin")
    assert r.status_code == 200
    assert b"<h1" in r.data


def test_developer_manual_accessible_to_admin(client_admin):
    r = client_admin.get("/docs/developer")
    assert r.status_code == 200
    assert b"<h1" in r.data


# ── Language switching ──────────────────────────────────────────


def test_user_manual_serves_italian_by_default(client_user):
    """User has locale=it; manual should be Italian."""
    r = client_user.get("/docs/user")
    body = r.data.decode()
    # Italian title or distinctive Italian phrase
    assert "Manuale utente" in body or "laboratorio" in body.lower()


def test_user_manual_language_toggle_to_english(client_user):
    """``?lang=en`` serves the English version regardless of user locale."""
    r = client_user.get("/docs/user?lang=en")
    assert r.status_code == 200
    body = r.data.decode()
    # English title or distinctive English phrase
    assert "User manual" in body or "laboratory" in body.lower()


def test_user_manual_language_toggle_back_to_italian(client_user):
    r = client_user.get("/docs/user?lang=it")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Manuale utente" in body or "Concetti chiave" in body


# ── 404 / edge cases ─────────────────────────────────────────────


def test_nonexistent_slug_returns_404(client_admin):
    r = client_admin.get("/docs/nonexistent")
    assert r.status_code == 404


def test_markdown_renders_tables(client_user):
    """Smoke test: the user manual contains tables, ensure the
    ``tables`` extension is active and they render to HTML."""
    r = client_user.get("/docs/user")
    assert r.status_code == 200
    assert b"<table" in r.data


def test_markdown_renders_code_blocks(client_admin):
    """Fenced code blocks (```bash ...) should render to <pre>/<code>."""
    r = client_admin.get("/docs/admin")
    assert r.status_code == 200
    body = r.data.decode()
    assert "<pre>" in body
    assert "<code" in body


def test_toc_is_generated(client_user):
    """The ``toc`` extension produces a Table of Contents that the
    template renders in the sidebar."""
    r = client_user.get("/docs/user")
    body = r.data.decode()
    # The sidebar header
    assert "In questa pagina" in body or "On this page" in body
    # And at least one anchor link from TOC
    assert 'href="#' in body
