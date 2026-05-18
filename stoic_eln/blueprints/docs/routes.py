"""Stoic — Docs viewer routes.

Three routes, one per manual:

* ``GET /docs/`` — index with cards for each available manual
* ``GET /docs/user`` — user manual (all logged-in users)
* ``GET /docs/admin`` — administrator manual (admin only)
* ``GET /docs/developer`` — developer manual (admin only)

Each route serves IT or EN based on the user's locale. There's
an explicit ``?lang=it|en`` override for users who want to switch
docs language without changing their UI locale.

The markdown source files live in ``docs/{it,en}/*.md`` at the
repo root. They are rendered to HTML at request time with the
``markdown`` library (``fenced_code``, ``tables``, ``toc``
extensions). Rendering is cheap and the docs are small (~15 KB
per file), so we skip caching.
"""
from __future__ import annotations

from functools import wraps
from pathlib import Path

import markdown as md
from flask import abort, current_app, render_template, request
from flask_babel import gettext as _
from flask_login import current_user, login_required

from stoic_eln.blueprints.docs import bp


# ── Filesystem resolution ───────────────────────────────────────


def _docs_root() -> Path:
    """Locate the docs/ folder at the repo root.

    Stoic's package lives at ``<repo>/stoic_eln/``, so ``docs/``
    is at ``<repo>/docs/``. We compute it from ``current_app.root_path``
    (= the package dir).
    """
    return Path(current_app.root_path).parent / "docs"


# Mapping of slug → (it_filename, en_filename, requires_admin).
# The slug is the URL fragment under /docs/, e.g. /docs/user.
_MANUAL_REGISTRY: dict[str, tuple[str, str, bool]] = {
    "user": ("manuale-utente.md", "user-manual.md", False),
    "admin": ("manuale-amministratore.md", "admin-manual.md", True),
    "developer": ("manuale-sviluppatore.md", "developer-manual.md", True),
}


# ── Helpers ─────────────────────────────────────────────────────


def _admin_required(view):
    """Decorator: 403 if current user is not an admin."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def _pick_language() -> str:
    """Resolve which language version of the manual to serve.

    Priority:
      1. ``?lang=it|en`` query string (explicit override)
      2. ``current_user.locale`` (the user's UI locale)
      3. Italian default
    """
    explicit = (request.args.get("lang") or "").strip().lower()
    if explicit in ("it", "en"):
        return explicit
    user_locale = (getattr(current_user, "locale", None) or "it").lower()
    return "en" if user_locale.startswith("en") else "it"


def _render_manual(slug: str):
    """Render the manual identified by ``slug`` for the chosen
    language. Returns the populated template response, or 404 if
    the file is missing."""
    entry = _MANUAL_REGISTRY.get(slug)
    if entry is None:
        abort(404)
    it_name, en_name, _requires_admin = entry

    lang = _pick_language()
    filename = en_name if lang == "en" else it_name
    path = _docs_root() / lang / filename

    if not path.is_file():
        # Fall back to the other language if the requested one
        # is missing (e.g. someone removed a file).
        other_lang = "it" if lang == "en" else "en"
        other_filename = it_name if lang == "en" else en_name
        other_path = _docs_root() / other_lang / other_filename
        if not other_path.is_file():
            abort(404)
        path = other_path
        lang = other_lang

    body_md = path.read_text(encoding="utf-8")

    html_renderer = md.Markdown(
        extensions=["fenced_code", "tables", "toc", "sane_lists"],
        extension_configs={
            "toc": {
                # Permalink so TOC anchors look polished and are
                # clickable from the sidebar.
                "permalink": False,
                "toc_depth": "2-3",
            },
        },
    )
    html = html_renderer.convert(body_md)
    toc_html = html_renderer.toc

    # The title is the first H1 of the markdown — extract it cheaply.
    # If there's no H1, fall back to a translated default.
    title = _DEFAULT_TITLES.get(slug, _("Manuale"))
    for line in body_md.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    return render_template(
        "docs/view.html",
        slug=slug,
        title=title,
        body_html=html,
        toc_html=toc_html,
        lang=lang,
        other_lang="it" if lang == "en" else "en",
        manual_registry=_MANUAL_REGISTRY,
        is_admin=bool(getattr(current_user, "is_admin", False)),
    )


# Slug → fallback title shown if the markdown has no top-level heading.
# Wrapped in lazy_gettext indirectly via the regular _() call at
# request time — these strings are still picked up by pybabel since
# they appear in dict values that flow into _().
_DEFAULT_TITLES: dict[str, str] = {
    "user": "Manuale utente",
    "admin": "Manuale amministratore",
    "developer": "Manuale sviluppatore",
}


# ── Routes ──────────────────────────────────────────────────────


@bp.route("/")
@login_required
def index():
    """Landing page listing the available manuals.

    Non-admins see only the user manual; admins see all three.
    """
    user_is_admin = bool(getattr(current_user, "is_admin", False))
    available: list[tuple[str, str, str]] = [
        # (slug, title, short description)
        ("user", _("Manuale utente"),
         _("Workflow tipico in laboratorio: sostanze, reazioni, "
           "run, miscele, etichette.")),
    ]
    if user_is_admin:
        available.append(
            ("admin", _("Manuale amministratore"),
             _("Installazione, gestione utenti, cifratura, backup, "
               "deployment."))
        )
        available.append(
            ("developer", _("Manuale sviluppatore"),
             _("Architettura, modelli, blueprint, testing, "
               "internazionalizzazione."))
        )
    return render_template(
        "docs/index.html",
        manuals=available,
        is_admin=user_is_admin,
    )


@bp.route("/user")
@login_required
def user_manual():
    """User manual — accessible to every authenticated user."""
    return _render_manual("user")


@bp.route("/admin")
@login_required
@_admin_required
def admin_manual():
    """Administrator manual — admin only."""
    return _render_manual("admin")


@bp.route("/developer")
@login_required
@_admin_required
def developer_manual():
    """Developer manual — admin only."""
    return _render_manual("developer")
