"""Section -> icon map shared by the sidebar and the page titles.

The sidebar in ``base.html`` and the icon next to each page title must
show the same Lucide glyph for the same section: that repetition is what
tells the operator where they are. ``tests/test_navigation.py`` parses
the sidebar and fails if the two drift apart.
"""

from __future__ import annotations

# Exact endpoints first (they override their blueprint), then blueprints.
_ENDPOINT_ICONS: dict[str, str] = {
    "main.dashboard": "layout-dashboard",
    "settings.users": "users",
    "settings.update_user_role": "users",
    "settings.audit_log": "shield-check",
    "settings.audit_log_export_csv": "shield-check",
    "settings.audit_log_export_pdf": "shield-check",
}

_BLUEPRINT_ICONS: dict[str, str] = {
    "substances": "flask-conical",
    "reactions": "arrow-left-right",
    "runs": "history",
    "mixtures": "beaker",
    "preps": "folder-clock",
    "procedures": "library",
    "inventory": "package",
    "orders": "shopping-cart",
    "suppliers": "book-user",
    "reports": "bar-chart-3",
    "docs": "book-open",
    "settings": "settings",
}


def section_icon(endpoint: str | None) -> str | None:
    """Return the Lucide icon name of the section ``endpoint`` belongs to."""
    if not endpoint:
        return None
    if endpoint in _ENDPOINT_ICONS:
        return _ENDPOINT_ICONS[endpoint]
    return _BLUEPRINT_ICONS.get(endpoint.split(".", 1)[0])
