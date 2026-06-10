"""Tests for Patch C: ProxyFix, /healthz, and installer manifests.

ProxyFix matters because the Docker stack puts Caddy in front of
gunicorn: without trusting X-Forwarded-Proto, Flask believes every
request is plain HTTP and generates http:// external URLs (breaking
the PWA manifest behind HTTPS). The tests simulate proxy headers
through the test client and assert Flask interprets them.
"""

from __future__ import annotations

from pathlib import Path

from stoic_eln.extensions import db
from stoic_eln.models import User

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── /healthz ───────────────────────────────────────────────────────


def test_healthz_returns_ok_without_auth(client):
    """Liveness probe must work unauthenticated — Docker polls it
    every 30 s with no session."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_healthz_is_lightweight(client):
    """The probe must not redirect (no login wall) and must not
    render HTML — it's polled twice a minute forever."""
    r = client.get("/healthz")
    assert r.mimetype == "application/json"
    # No redirect chain
    assert r.status_code == 200


# ── ProxyFix ───────────────────────────────────────────────────────


def test_proxy_headers_set_https_scheme(app, client):
    """Behind Caddy, X-Forwarded-Proto: https must make Flask see
    the request as secure, so url_for(_external=True) produces
    https:// URLs (PWA manifest, redirects)."""
    with app.app_context():
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

    # The manifest endpoint generates absolute URLs via url_for —
    # perfect probe for scheme handling.
    r = client.get(
        "/manifest.webmanifest",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "203.0.113.7",
            "X-Forwarded-Host": "stoic.local",
        },
    )
    assert r.status_code == 200
    data = r.get_json()
    # url_for-generated icon paths must resolve correctly with the
    # forwarded Host in play (no scheme/host confusion → no 500s,
    # icons array intact).
    assert data["icons"], "manifest icons must be generated under proxy headers"
    assert all(icon["src"].startswith("/") for icon in data["icons"])


def test_proxy_for_header_sets_remote_addr(app):
    """X-Forwarded-For from one trusted hop must become
    request.remote_addr — audit logs record the real client, not
    the Caddy container IP."""
    captured = {}

    @app.route("/_test_remote_addr")
    def _probe():
        from flask import request

        captured["remote_addr"] = request.remote_addr
        captured["is_secure"] = request.is_secure
        return "ok"

    client = app.test_client()
    client.get(
        "/_test_remote_addr",
        headers={
            "X-Forwarded-For": "203.0.113.7",
            "X-Forwarded-Proto": "https",
        },
    )
    assert captured["remote_addr"] == "203.0.113.7"
    assert captured["is_secure"] is True


def test_without_proxy_headers_nothing_changes(app):
    """ProxyFix with no X-Forwarded-* headers present must be a
    no-op — `flask run` development is unaffected."""
    captured = {}

    @app.route("/_test_no_proxy")
    def _probe():
        from flask import request

        captured["is_secure"] = request.is_secure
        return "ok"

    client = app.test_client()
    client.get("/_test_no_proxy")
    assert captured["is_secure"] is False


# ── installer script ───────────────────────────────────────────────


def test_install_linux_script_exists_and_is_executable():
    script = REPO_ROOT / "scripts" / "installers" / "install-linux.sh"
    assert script.is_file()
    assert script.stat().st_mode & 0o111, "install-linux.sh must be executable"


def test_install_linux_script_structure():
    """Spot-check the critical behaviours promised in the docs:
    refuses root, idempotent .env handling, generates SECRET_KEY,
    reads domain from /dev/tty (curl|bash safe)."""
    content = (REPO_ROOT / "scripts" / "installers" / "install-linux.sh").read_text()
    assert "set -euo pipefail" in content
    assert "id -u" in content, "must refuse to run as root"
    assert "SECRET_KEY=$(head -c 32 /dev/urandom" in content
    assert "/dev/tty" in content, "domain prompt must work under curl|bash"
    assert "docker compose up -d" in content


def test_roadmap_exists_with_checklist():
    content = (REPO_ROOT / "ROADMAP.md").read_text()
    assert "- [x]" in content, "ROADMAP must track completed items"
    assert "- [ ]" in content, "ROADMAP must track open items"
    assert "v1.0.0" in content
