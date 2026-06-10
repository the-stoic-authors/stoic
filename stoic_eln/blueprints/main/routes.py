"""Stoic ELN — Main routes (dashboard, root)."""

from flask import redirect, render_template, url_for
from flask_login import current_user, login_required

from stoic_eln.blueprints.main import bp


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models.reaction import Reaction
    from stoic_eln.models.run import Run
    from stoic_eln.services.inventory_alerts import get_summary
    from stoic_eln.services.shopping_list import build_shopping_list

    summary = get_summary()
    # Top 5 shopping suggestions (open orders are already excluded by
    # the service since patch 4.1)
    suggestions_all = build_shopping_list()
    shopping_top5 = suggestions_all[:5]
    shopping_total_count = len(suggestions_all)

    # Reaction count: published + non-archived
    n_reactions = (
        db.session.query(Reaction)
        .filter(Reaction.status == "published")
        .filter(Reaction.is_archived.is_(False))
        .count()
    )
    n_runs_completed = db.session.query(Run).filter(Run.status == "completed").count()

    # Recent audit events — admin only
    recent_audit_events: list = []
    label_for_action = None
    from flask_login import current_user

    if current_user.is_authenticated and getattr(current_user, "is_admin", False):
        from stoic_eln.services.audit_query import (
            recent_events,
            label_for_action as _lf,
        )

        recent_audit_events = recent_events(n=8)
        label_for_action = _lf

    return render_template(
        "main/dashboard.html",
        summary=summary,
        n_reactions=n_reactions,
        n_runs_completed=n_runs_completed,
        today=date.today(),
        shopping_top5=shopping_top5,
        shopping_total_count=shopping_total_count,
        recent_audit_events=recent_audit_events,
        label_for_action=label_for_action,
    )


# ── PWA support ────────────────────────────────────────────────────


@bp.route("/manifest.webmanifest")
def manifest():
    """Serve the Web App Manifest for Progressive Web App support.

    The manifest is rendered dynamically so the installable app
    name reflects the lab name set during onboarding (falling back
    to "Stoic" when not set). All other fields are static.

    The MIME type ``application/manifest+json`` is the spec value;
    Safari is tolerant of ``application/json`` too, but we go by
    the book.
    """
    from flask import current_app, jsonify, url_for

    from stoic_eln.blueprints.onboarding.routes import get_lab_name

    lab_name = get_lab_name(default=current_app.config.get("LAB_NAME", "Stoic"))

    manifest_data = {
        "name": f"{lab_name} — Stoic",
        "short_name": lab_name if len(lab_name) <= 12 else "Stoic",
        "description": "Electronic Lab Notebook + LIMS for small chemistry labs.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": "#1F3864",
        "background_color": "#1F3864",
        "icons": [
            {
                "src": url_for("static", filename="img/pwa/icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("static", filename="img/pwa/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("static", filename="img/pwa/icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
        "lang": "it",
        "categories": ["productivity", "science"],
    }

    response = jsonify(manifest_data)
    response.mimetype = "application/manifest+json"
    return response


@bp.route("/healthz")
def healthz():
    """Lightweight liveness probe for Docker/compose/orchestrators.

    Deliberately minimal: no template rendering, no DB query, no
    auth. It answers "is the WSGI worker alive and serving?" — the
    only question a HEALTHCHECK needs. Anything heavier (DB
    reachability, disk space) belongs in a separate readiness
    probe if we ever need one.
    """
    return {"status": "ok"}, 200
