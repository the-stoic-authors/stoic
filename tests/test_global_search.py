"""Tests for the global search service and command-palette endpoint."""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.substance import Substance
from stoic_eln.models.user import User


def _login(client, app):
    with app.app_context():
        if db.session.query(User).filter_by(username="admin").first() is None:
            u = User(
                username="admin",
                full_name="Admin",
                operator_code="ADM",
                is_admin=True,
                is_active=True,
                locale="it",
            )
            u.set_password("password123")
            db.session.add(u)
            db.session.commit()
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "password123", "submit": "Accedi"},
    )


# ── Service-level tests ─────────────────────────────────────────────────────


def test_search_requires_two_chars(app):
    from stoic_eln.services import global_search

    with app.app_context():
        assert global_search.search("") == []
        assert global_search.search("a") == []


def test_search_finds_substance_by_name(app):
    from stoic_eln.services import global_search

    with app.app_context():
        db.session.add(Substance(name="Caffeine", molecular_formula="C8H10N4O2"))
        db.session.commit()

        results = global_search.search("caff")
        assert any(r["type"] == "substance" and r["title"] == "Caffeine" for r in results)


def test_search_finds_substance_by_cas(app):
    from stoic_eln.services import global_search

    with app.app_context():
        db.session.add(Substance(name="Acetone", cas_number="67-64-1"))
        db.session.commit()

        results = global_search.search("67-64")
        assert any(r["type"] == "substance" for r in results)


def test_search_excludes_inactive_substance(app):
    from stoic_eln.services import global_search

    with app.app_context():
        db.session.add(Substance(name="Ghostane", is_active=False))
        db.session.commit()

        results = global_search.search("ghostane")
        assert results == []


def test_search_excludes_draft_reactions(app):
    from stoic_eln.services import global_search

    with app.app_context():
        db.session.add(Reaction(code="RXN-DRAFT", title="Secret Draft Coupling", status="draft"))
        db.session.add(Reaction(code="RXN-PUB", title="Published Coupling", status="published"))
        db.session.commit()

        results = global_search.search("coupling")
        titles = {r["title"] for r in results if r["type"] == "reaction"}
        assert "Published Coupling" in titles
        assert "Secret Draft Coupling" not in titles


def test_per_type_limit_caps_results(app):
    from stoic_eln.services import global_search

    with app.app_context():
        for i in range(20):
            db.session.add(Substance(name=f"Polytest-{i:02d}"))
        db.session.commit()

        results = global_search.search("polytest", limit_per_type=6)
        subs = [r for r in results if r["type"] == "substance"]
        assert len(subs) == 6


# ── Endpoint tests ──────────────────────────────────────────────────────────


def test_search_endpoint_requires_auth(client):
    resp = client.get("/search/?q=caffeine", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_search_endpoint_returns_json_with_urls(client, app):
    with app.app_context():
        db.session.add(Substance(name="Toluene", molecular_formula="C7H8"))
        db.session.commit()

    _login(client, app)
    resp = client.get("/search/?q=tolu")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["query"] == "tolu"
    hit = next(r for r in data["results"] if r["title"] == "Toluene")
    assert hit["type"] == "substance"
    assert hit["type_label"]  # translated label is filled in
    assert hit["url"].startswith("/substances/")


def test_search_endpoint_short_query_returns_empty(client, app):
    _login(client, app)
    resp = client.get("/search/?q=a")
    assert resp.status_code == 200
    assert resp.get_json()["results"] == []
