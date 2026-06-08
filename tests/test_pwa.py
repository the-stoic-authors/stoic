"""Tests for the Progressive Web App support (manifest + meta tags).

The manifest is served dynamically by ``main.manifest`` at
``/manifest.webmanifest`` and reflects the lab name set during
onboarding. The base template includes the apple-touch-icon,
apple-mobile-web-app-* meta tags and the theme-color so that
'Add to Home Screen' on iOS produces a clean install.
"""

from __future__ import annotations

import json

from stoic_eln.extensions import db
from stoic_eln.models import User
from stoic_eln.models.settings import AppSetting


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
    client.post("/auth/login", data={"username": "r", "password": "x", "submit": "x"})


# ── Manifest endpoint ──────────────────────────────────────────────


def test_manifest_endpoint_returns_valid_json(app, client):
    """The manifest URL is publicly accessible (the browser fetches
    it before login) and returns the spec-compliant MIME type."""
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.mimetype == "application/manifest+json"

    data = json.loads(r.get_data(as_text=True))
    # Required fields per Web App Manifest spec
    assert "name" in data
    assert "short_name" in data
    assert "start_url" in data
    assert "display" in data
    assert "icons" in data and len(data["icons"]) >= 2


def test_manifest_includes_required_icon_sizes(app, client):
    r = client.get("/manifest.webmanifest")
    data = json.loads(r.get_data(as_text=True))
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert "192x192" in sizes
    assert "512x512" in sizes


def test_manifest_has_maskable_icon(app, client):
    """At least one icon must declare ``purpose: maskable`` so the
    PWA installer can crop it into platform-specific shapes
    (rounded square on iOS, circle on Android, etc.)."""
    r = client.get("/manifest.webmanifest")
    data = json.loads(r.get_data(as_text=True))
    purposes = {icon.get("purpose", "") for icon in data["icons"]}
    assert "maskable" in purposes


def test_manifest_picks_up_lab_name_from_appsetting(app, client):
    """When the wizard has set a lab name, it appears in the
    manifest's name field, so the installed app shows the lab
    name on the home screen."""
    with app.app_context():
        AppSetting.set("lab.name", "Acme Labs")

    r = client.get("/manifest.webmanifest")
    data = json.loads(r.get_data(as_text=True))
    assert "Acme Labs" in data["name"]


def test_manifest_short_name_falls_back_for_long_lab_names(app, client):
    """The short_name appears on the home screen icon (≤ ~12 chars
    visible on most platforms). For very long lab names we fall
    back to "Stoic"."""
    with app.app_context():
        AppSetting.set("lab.name", "Dipartimento di Chimica Organica e Industriale")

    r = client.get("/manifest.webmanifest")
    data = json.loads(r.get_data(as_text=True))
    # name keeps the full lab name; short_name falls back
    assert data["short_name"] == "Stoic"


def test_manifest_uses_default_when_no_lab_name_set(app, client):
    r = client.get("/manifest.webmanifest")
    data = json.loads(r.get_data(as_text=True))
    # Falls back to LAB_NAME (or "Stoic") — the test config doesn't
    # override LAB_NAME so we just check the name is non-empty
    assert data["name"]
    assert data["short_name"]


# ── Base template tags ─────────────────────────────────────────────


def test_base_template_includes_manifest_link(app, client):
    with app.app_context():
        _make_admin()
    _login(client)

    r = client.get("/dashboard")
    body = r.get_data(as_text=True)
    assert 'rel="manifest"' in body
    assert "/manifest.webmanifest" in body


def test_base_template_includes_apple_touch_icon(app, client):
    with app.app_context():
        _make_admin()
    _login(client)

    r = client.get("/dashboard")
    body = r.get_data(as_text=True)
    assert 'rel="apple-touch-icon"' in body
    assert "icon-180.png" in body


def test_base_template_includes_pwa_meta_tags(app, client):
    """The four iOS meta tags that make 'Add to Home Screen' produce
    a fullscreen app with the right title and status bar style."""
    with app.app_context():
        _make_admin()
    _login(client)

    r = client.get("/dashboard")
    body = r.get_data(as_text=True)
    assert 'name="apple-mobile-web-app-capable"' in body
    assert 'name="apple-mobile-web-app-status-bar-style"' in body
    assert 'name="apple-mobile-web-app-title"' in body
    assert 'name="theme-color"' in body


def test_apple_mobile_web_app_title_reflects_lab_name(app, client):
    with app.app_context():
        _make_admin()
        AppSetting.set("lab.name", "Lab Rossi")
    _login(client)

    r = client.get("/dashboard")
    body = r.get_data(as_text=True)
    assert 'content="Lab Rossi"' in body


# ── Static asset availability ──────────────────────────────────────


def test_pwa_icon_files_are_served(app, client):
    """The static handler must successfully serve the PNG icons."""
    for path in (
        "/static/img/pwa/icon-192.png",
        "/static/img/pwa/icon-512.png",
        "/static/img/pwa/icon-180.png",
        "/static/img/pwa/icon-maskable-512.png",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.mimetype == "image/png", path
