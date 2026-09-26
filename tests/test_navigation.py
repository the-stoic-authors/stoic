"""Section icons and the colour grammar hooks (v1.5.5).

* The sidebar in base.html and ``navigation.section_icon`` must agree:
  the icon next to a page title is only useful if it is the same glyph
  the sidebar highlights.
* A run in progress has its own badge colour ("running"), separate from
  the "primary" used by role badges.
* List pages render the section icon inside the page title.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stoic_eln.models.run import STATUS_COMPLETED, STATUS_DRAFT, STATUS_IN_PROGRESS, Run
from stoic_eln.navigation import section_icon

BASE_HTML = Path(__file__).resolve().parents[1] / "stoic_eln" / "templates" / "base.html"


def _sidebar_pairs() -> list[tuple[str, str]]:
    """(endpoint condition, icon) for every nav-item in the sidebar."""
    html = BASE_HTML.read_text(encoding="utf-8")
    pairs = []
    for m in re.finditer(
        r'<a class="nav-item \{% if (.*?) %\}active.*?data-lucide="([a-z0-9-]+)"', html, re.S
    ):
        pairs.append((m.group(1), m.group(2)))
    return pairs


def test_sidebar_is_parsed():
    assert len(_sidebar_pairs()) >= 14


def test_sidebar_icons_match_section_icon():
    for cond, icon in _sidebar_pairs():
        eq = re.search(r"request\.endpoint == '([\w.]+)'", cond)
        prefix = re.search(r"startswith\('([\w]+)\.'\)", cond)
        listed = re.search(r"request\.endpoint in \(([^)]*)\)", cond)
        if eq:
            endpoints = [eq.group(1)]
        elif listed:
            endpoints = re.findall(r"'([\w.]+)'", listed.group(1))
        elif prefix:
            endpoints = [f"{prefix.group(1)}.list_view", f"{prefix.group(1)}.detail"]
        else:
            pytest.fail(f"sidebar condition not understood: {cond}")
        for ep in endpoints:
            assert section_icon(ep) == icon, (ep, icon)


def test_section_icon_edge_cases():
    assert section_icon(None) is None
    assert section_icon("") is None
    assert section_icon("static") is None
    assert section_icon("settings.audit_log") == "shield-check"
    assert section_icon("settings.backups") == "settings"


def test_run_status_colours():
    run = Run()
    run.status = STATUS_IN_PROGRESS
    assert run.status_color == "running"
    run.status = STATUS_DRAFT
    assert run.status_color == "secondary"
    run.status = STATUS_COMPLETED
    assert run.status_color == "success"


def test_css_defines_running_badge():
    css = (BASE_HTML.parents[1] / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".badge.text-bg-running" in css


@pytest.fixture
def logged_client(client, admin_user):
    client.post("/auth/login", data={"username": "testadmin", "password": "testpassword123"})
    return client


@pytest.mark.parametrize(
    ("url", "icon"),
    [
        ("/dashboard", "layout-dashboard"),
        ("/runs/", "history"),
        ("/inventory/", "package"),
        ("/reactions/", "arrow-left-right"),
    ],
)
def test_page_title_carries_section_icon(logged_client, url, icon):
    resp = logged_client.get(url)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    m = re.search(r'<h1 class="page-title[^"]*">(.*?)</h1>', html, re.S)
    assert m, "page title missing"
    assert f'data-lucide="{icon}"' in m.group(1)
