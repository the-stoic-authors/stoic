"""Stoic — Attachment routes (Settimana 6 patch 10).

Endpoints:

  POST /attachments/<entity_type>/<entity_id>/new   — upload (HTMX-friendly)
  GET  /attachments/<id>/download                   — force download
  GET  /attachments/<id>/preview                    — inline (images/PDF)
  POST /attachments/<id>/delete                     — uploader or admin

Authorisation:
  - Anyone logged in can upload.
  - Uploader can delete their own attachments; admins can delete anyone's.
  - All authenticated users can download/preview.
"""

from __future__ import annotations

from flask import (
    abort, flash, redirect, render_template, request, send_file, url_for,
)
from flask_babel import gettext as _
from flask_login import current_user, login_required

from stoic_eln.blueprints.attachments import bp
from stoic_eln.extensions import db
from stoic_eln.models import InventoryItem, Reaction, Run, Substance
from stoic_eln.models.attachment import (
    ATTACHMENT_ENTITY_TYPES, Attachment,
)
from stoic_eln.models.mixture import Mixture
from stoic_eln.models.mixture_prep import MixturePrep
from stoic_eln.services import attachments as att_service
from stoic_eln.services.attachments import AttachmentError
from stoic_eln.services.audit import log_event


# ── Entity resolver ────────────────────────────────────────────────


_ENTITY_MODEL = {
    "run": Run,
    "reaction": Reaction,
    "substance": Substance,
    "inventory_item": InventoryItem,
    "mixture": Mixture,
    "mixture_prep": MixturePrep,
}


def _resolve_entity(entity_type: str, entity_id: int):
    """Return the entity object or 404. Validates entity_type."""
    if entity_type not in ATTACHMENT_ENTITY_TYPES:
        abort(404)
    model = _ENTITY_MODEL[entity_type]
    obj = db.session.get(model, entity_id)
    if obj is None:
        abort(404)
    return obj


def _redirect_to_entity(entity_type: str, entity_id: int):
    """Where to go after a non-HTMX form submission.

    Note: there is no ``inventory.detail`` route; lots are edited via
    ``inventory.edit``, which is the canonical landing page for a lot.
    """
    if entity_type == "run":
        return redirect(url_for("runs.detail", run_id=entity_id))
    if entity_type == "reaction":
        return redirect(url_for("reactions.detail", reaction_id=entity_id))
    if entity_type == "substance":
        return redirect(url_for("substances.detail", substance_id=entity_id))
    if entity_type == "inventory_item":
        return redirect(url_for("inventory.edit", item_id=entity_id))
    if entity_type == "mixture":
        return redirect(url_for("mixtures.detail", mixture_id=entity_id))
    if entity_type == "mixture_prep":
        return redirect(url_for("preps.detail", prep_id=entity_id))
    return redirect("/")


def _render_list_partial(entity_type: str, entity_id: int):
    """Render the attachments list partial, used as HTMX response."""
    attachments = att_service.list_attachments(entity_type, entity_id)
    return render_template(
        "attachments/_list.html",
        attachments=attachments,
        entity_type=entity_type,
        entity_id=entity_id,
    )


# ── Upload ─────────────────────────────────────────────────────────


@bp.route("/<entity_type>/<int:entity_id>/new", methods=["POST"])
@login_required
def upload(entity_type: str, entity_id: int):
    _resolve_entity(entity_type, entity_id)

    file = request.files.get("file")
    caption = (request.form.get("caption") or "").strip() or None

    if file is None or not (file.filename or "").strip():
        flash(_("Nessun file selezionato."), "warning")
        if request.headers.get("HX-Request"):
            return _render_list_partial(entity_type, entity_id)
        return _redirect_to_entity(entity_type, entity_id)

    try:
        att = att_service.save_upload(
            file=file,
            entity_type=entity_type,
            entity_id=entity_id,
            uploaded_by_id=current_user.id,
            caption=caption,
        )
    except AttachmentError as exc:
        flash(str(exc), "danger")
        if request.headers.get("HX-Request"):
            return _render_list_partial(entity_type, entity_id)
        return _redirect_to_entity(entity_type, entity_id)

    log_event(
        action="create", entity_type="attachment", entity_id=att.id,
        details={
            "target_type": entity_type, "target_id": entity_id,
            "filename": att.filename, "size_bytes": att.size_bytes,
        },
    )
    flash(_("Allegato caricato."), "success")

    if request.headers.get("HX-Request"):
        return _render_list_partial(entity_type, entity_id)
    return _redirect_to_entity(entity_type, entity_id)


# ── Download / preview ─────────────────────────────────────────────


def _send_attachment(att: Attachment, *, as_attachment: bool):
    """Send the file with the original filename."""
    path = att_service.storage_path(att)
    if not path.exists():
        abort(404)
    return send_file(
        str(path),
        mimetype=att.mime_type or "application/octet-stream",
        as_attachment=as_attachment,
        download_name=att.filename,
        max_age=0,
    )


@bp.route("/<int:attachment_id>/download", methods=["GET"])
@login_required
def download(attachment_id: int):
    att = db.session.get(Attachment, attachment_id)
    if att is None:
        abort(404)
    return _send_attachment(att, as_attachment=True)


@bp.route("/<int:attachment_id>/preview", methods=["GET"])
@login_required
def preview(attachment_id: int):
    att = db.session.get(Attachment, attachment_id)
    if att is None:
        abort(404)
    # Inline only for images and PDFs; everything else falls back to
    # download (browser would just save it anyway).
    inline = att.is_image or att.is_pdf
    return _send_attachment(att, as_attachment=not inline)


# ── Delete ─────────────────────────────────────────────────────────


@bp.route("/<int:attachment_id>/delete", methods=["POST"])
@login_required
def delete(attachment_id: int):
    att = db.session.get(Attachment, attachment_id)
    if att is None:
        abort(404)

    is_admin = bool(getattr(current_user, "is_admin", False))
    is_uploader = (att.uploaded_by_id == current_user.id)
    if not (is_admin or is_uploader):
        abort(403)

    entity_type, entity_id = att.entity_type, att.entity_id
    log_event(
        action="delete", entity_type="attachment", entity_id=att.id,
        details={
            "target_type": entity_type, "target_id": entity_id,
            "filename": att.filename, "uploaded_by_id": att.uploaded_by_id,
        },
    )
    att_service.delete_attachment(att)

    if request.headers.get("HX-Request"):
        return _render_list_partial(entity_type, entity_id)
    return _redirect_to_entity(entity_type, entity_id)
