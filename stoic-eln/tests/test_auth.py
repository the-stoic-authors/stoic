"""Smoke tests for Week 1 deliverables: app boot, auth, layout."""

from __future__ import annotations


def test_app_creates(app):
    assert app is not None
    assert app.config["TESTING"] is True


def test_login_page_renders(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b"Stoic" in resp.data
    assert b"Lab notebook, refactored" in resp.data


def test_root_redirects_to_login_when_anonymous(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_dashboard_requires_auth(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_login_with_correct_credentials(client, admin_user):
    resp = client.post(
        "/auth/login",
        data={"username": "testadmin", "password": "testpassword123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


def test_login_with_wrong_password(client, admin_user):
    resp = client.post(
        "/auth/login",
        data={"username": "testadmin", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post(
        "/auth/login",
        data={"username": "ghost", "password": "anything"},
    )
    assert resp.status_code == 401


def test_logged_in_dashboard(client, admin_user):
    client.post(
        "/auth/login",
        data={"username": "testadmin", "password": "testpassword123"},
    )
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"Test Admin" in resp.data


def test_logout(client, admin_user):
    client.post(
        "/auth/login",
        data={"username": "testadmin", "password": "testpassword123"},
    )
    resp = client.get("/auth/logout", follow_redirects=False)
    assert resp.status_code == 302
    # After logout, dashboard should redirect to login
    resp = client.get("/dashboard")
    assert resp.status_code == 302


def test_locale_switch_sets_cookie(client):
    resp = client.get("/auth/locale/en", follow_redirects=False)
    assert resp.status_code == 302
    cookie = resp.headers.get("Set-Cookie", "")
    assert "locale=en" in cookie


def test_theme_switch_sets_cookie(client):
    resp = client.get("/auth/theme/dark", follow_redirects=False)
    assert resp.status_code == 302
    cookie = resp.headers.get("Set-Cookie", "")
    assert "theme=dark" in cookie
