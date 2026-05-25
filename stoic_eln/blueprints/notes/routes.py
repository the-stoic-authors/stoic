"""Stoic — Notes routes (Settimana 6 patch 9).

Endpoints (all HTMX-friendly):

  POST /notes/<entity_type>/<entity_id>/new       — create a note
  POST /notes/<note_id>/edit                      — edit (author only)
  POST /notes/<note_id>/delete                    — delete (admin only)
  GET  /notes/<note_id>/edit-form                 — return edit form HTML

Authorisation:
  - Anyone logged in can create.
  - Only the author can edit (and only the body, not entity).
  - Only admins can delete (hard delete; audit log preserves history).
"""

from __future__ import annotations

from datetime import datetime, UTC

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from stoic_eln.blueprints.notes import bp
from stoic_eln.extensions import db
from stoic_eln.models import Reaction, Run, Substance
from stoic_eln.models.note import NOTE_ENTITY_TYPES, Note
from stoic_eln.services.audit import log_event
from stoic_eln.services.notes import list_notes


# ── Entity resolver ────────────────────────────────────────────────


def _resolve_entity(entity_type: str, entity_id: int):
    """Return the entity object or 404. Validates entity_type."""
    if entity_type not in NOTE_ENTITY_TYPES:
        abort(404)
    model = {
        "run": Run,
        "reaction": Reaction,
        "substance": Substance,
    }[entity_type]
    obj = db.session.get(model, entity_id)
    if obj is None:
        abort(404)
    return obj


def _redirect_to_entity(entity_type: str, entity_id: int):
    """Where to go after a non-HTMX form submission."""
    if entity_type == "run":
        return redirect(url_for("runs.detail", run_id=entity_id))
    if entity_type == "reaction":
        return redirect(url_for("reactions.detail", reaction_id=entity_id))
    if entity_type == "substance":
        return redirect(url_for("substances.detail", substance_id=entity_id))
    return redirect("/")


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _render_thread_partial(entity_type: str, entity_id: int):
    """Render the notes thread partial, used as HTMX response."""
    notes = list_notes(entity_type, entity_id)
    return render_template(
        "notes/_thread.html",
        notes=notes,
        entity_type=entity_type,
        entity_id=entity_id,
    )


# ── Create ─────────────────────────────────────────────────────────


@bp.route("/<entity_type>/<int:entity_id>/new", methods=["POST"])
@login_required
def create(entity_type: str, entity_id: int):
    _resolve_entity(entity_type, entity_id)

    body = (request.form.get("body") or "").strip()
    if not body:
        flash(_("Il commento non può essere vuoto."), "warning")
        if request.headers.get("HX-Request"):
            return _render_thread_partial(entity_type, entity_id)
        return _redirect_to_entity(entity_type, entity_id)

    # Hard limit to keep things sane (about 5 paragraphs of dense text)
    if len(body) > 10_000:
        flash(_("Il commento è troppo lungo (max 10000 caratteri)."), "danger")
        if request.headers.get("HX-Request"):
            return _render_thread_partial(entity_type, entity_id)
        return _redirect_to_entity(entity_type, entity_id)

    note = Note(
        entity_type=entity_type,
        entity_id=entity_id,
        body=body,
        author_id=current_user.id,
    )
    db.session.add(note)
    db.session.commit()
    log_event(
        action="create",
        entity_type="note",
        entity_id=note.id,
        details={"target_type": entity_type, "target_id": entity_id},
    )

    if request.headers.get("HX-Request"):
        return _render_thread_partial(entity_type, entity_id)
    return _redirect_to_entity(entity_type, entity_id)


# ── Edit (author only) ─────────────────────────────────────────────


@bp.route("/<int:note_id>/edit-form", methods=["GET"])
@login_required
def edit_form(note_id: int):
    """Return the edit form HTML for inline replacement (HTMX)."""
    note = db.session.get(Note, note_id)
    if note is None:
        abort(404)
    if note.author_id != current_user.id:
        abort(403)
    return render_template("notes/_edit_form.html", note=note)


@bp.route("/<int:note_id>/view", methods=["GET"])
@login_required
def view(note_id: int):
    """Return the read-only single-note partial (used for cancel from edit)."""
    note = db.session.get(Note, note_id)
    if note is None:
        abort(404)
    return render_template("notes/_note.html", n=note)


@bp.route("/<int:note_id>/edit", methods=["POST"])
@login_required
def edit(note_id: int):
    note = db.session.get(Note, note_id)
    if note is None:
        abort(404)
    if note.author_id != current_user.id:
        abort(403)

    body = (request.form.get("body") or "").strip()
    if not body:
        flash(_("Il commento non può essere vuoto."), "warning")
        if request.headers.get("HX-Request"):
            return _render_thread_partial(note.entity_type, note.entity_id)
        return _redirect_to_entity(note.entity_type, note.entity_id)

    if len(body) > 10_000:
        flash(_("Il commento è troppo lungo (max 10000 caratteri)."), "danger")
        if request.headers.get("HX-Request"):
            return _render_thread_partial(note.entity_type, note.entity_id)
        return _redirect_to_entity(note.entity_type, note.entity_id)

    if body == note.body:
        # No-op: don't bump updated_at if nothing changed
        if request.headers.get("HX-Request"):
            return _render_thread_partial(note.entity_type, note.entity_id)
        return _redirect_to_entity(note.entity_type, note.entity_id)

    note.body = body
    note.updated_at = _now_utc()
    db.session.commit()
    log_event(
        action="update",
        entity_type="note",
        entity_id=note.id,
        details={"target_type": note.entity_type, "target_id": note.entity_id},
    )

    if request.headers.get("HX-Request"):
        return _render_thread_partial(note.entity_type, note.entity_id)
    return _redirect_to_entity(note.entity_type, note.entity_id)


# ── Delete (admin only) ────────────────────────────────────────────


@bp.route("/<int:note_id>/delete", methods=["POST"])
@login_required
def delete(note_id: int):
    note = db.session.get(Note, note_id)
    if note is None:
        abort(404)
    if not getattr(current_user, "is_admin", False):
        abort(403)

    entity_type, entity_id, author_id = (
        note.entity_type,
        note.entity_id,
        note.author_id,
    )
    log_event(
        action="delete",
        entity_type="note",
        entity_id=note.id,
        details={"target_type": entity_type, "target_id": entity_id, "author_id": author_id},
    )
    db.session.delete(note)
    db.session.commit()

    if request.headers.get("HX-Request"):
        return _render_thread_partial(entity_type, entity_id)
    return _redirect_to_entity(entity_type, entity_id)
