"""Stoic — Attachments service (Settimana 6 patch 10).

Storage layout
~~~~~~~~~~~~~~
Files live under ``config['ATTACHMENTS_DIR']`` (resolved relative to
PROJECT_ROOT when not absolute). On-disk filenames are
``{sha256[:16]}_{safe_filename}``, which gives us:

  * Cheap content-addressed dedup: if the user uploads the same file
    twice (across different entities or even the same one), we still
    only store one copy.
  * Safe-by-construction names: the sha prefix avoids collisions even
    for files with the same display name, and the safe_filename strips
    path separators.

A row is created per attachment. When a row is deleted, the file on
disk is removed *only* when no other row references the same
``storage_filename`` — handled by :func:`delete_attachment`.

Validation
~~~~~~~~~~
Two-stage filter on uploads:

  1. **Denylist** (executable / scriptable): always rejected, regardless
     of what the user types as the extension. ``.exe``, ``.html``,
     ``.svg`` (XSS risk), ``.js``, ``.py``, etc.
  2. **Allowlist**: lab-relevant types only. PDFs, common images,
     instrument data formats (csv/xlsx/jdx/mol/raw/mzML/...), archives.

Both checks happen on the user-provided filename's extension. We don't
sniff content because most lab-data formats look like opaque blobs.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path
from typing import IO

from flask import current_app
from werkzeug.datastructures import FileStorage

from stoic_eln.extensions import db
from stoic_eln.models.attachment import ATTACHMENT_ENTITY_TYPES, Attachment


# ── Constants ─────────────────────────────────────────────────────────


# Allowed extensions (lowercase, no leading dot). Conservative whitelist
# tilted toward chemistry-lab data: documents, images, instrument output,
# light archive formats. Adding entries here is a one-line edit.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Documents
        "pdf",
        "txt",
        "md",
        "rtf",
        "doc",
        "docx",
        "odt",
        # Spreadsheets / tabular
        "csv",
        "tsv",
        "xls",
        "xlsx",
        "ods",
        # Images
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "tif",
        "tiff",
        "bmp",
        "heic",
        # Lab / instrument data
        "jdx",
        "dx",  # JCAMP-DX (NMR/IR)
        "mol",
        "sdf",
        "mol2",  # Molecule files
        "cdx",
        "cdxml",  # ChemDraw
        "raw",
        "mzml",
        "mzxml",  # Mass spec
        "fid",  # NMR raw
        "cif",  # Crystallography
        # Archives (so users can group e.g. an NMR fid directory)
        "zip",
        "tar",
        "gz",
        "tgz",
        "7z",
    }
)


# Denied extensions: explicitly executable / scriptable / risky.
# Even if a user renamed an .exe to something allowed, the extension
# check on the typed filename would still pass — we accept that
# trade-off; we're a single-tenant lab tool, not a public file host.
DENIED_EXTENSIONS: frozenset[str] = frozenset(
    {
        "exe",
        "com",
        "bat",
        "cmd",
        "msi",
        "scr",
        "ps1",
        "sh",
        "bash",
        "zsh",
        "fish",
        "py",
        "pyc",
        "pyo",
        "pyd",
        "js",
        "mjs",
        "cjs",
        "html",
        "htm",
        "xhtml",
        "svg",  # XSS via embedded scripts
        "php",
        "phtml",
        "jar",
        "war",
        "class",
        "vbs",
        "wsf",
        "hta",
        "dll",
        "so",
        "dylib",
        "lnk",
        "app",
    }
)


# ── Errors ────────────────────────────────────────────────────────────


class AttachmentError(Exception):
    """Raised when an attachment can't be saved (size / type / empty / IO)."""


# ── Path helpers ──────────────────────────────────────────────────────


def storage_dir() -> Path:
    """Resolve the on-disk attachments directory, creating it if needed.

    If ``ATTACHMENTS_DIR`` in config is an absolute path, it's used as-is.
    Otherwise it's interpreted relative to PROJECT_ROOT (i.e. the
    repository root).
    """
    raw = current_app.config.get("ATTACHMENTS_DIR", "data/attachments")
    p = Path(raw)
    if not p.is_absolute():
        # PROJECT_ROOT == parent of the stoic_eln package
        from stoic_eln.config import PROJECT_ROOT

        p = PROJECT_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def storage_path(att: Attachment) -> Path:
    """Absolute on-disk path for an attachment row."""
    return storage_dir() / att.storage_filename


# ── Filename sanitisation ─────────────────────────────────────────────


_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._\-]+")


def _safe_filename(name: str) -> str:
    """Strip path components and unsafe characters; preserve extension.

    The result is safe to use as a basename on disk: ASCII-only,
    no slashes/backslashes, no leading dot. Empty input becomes
    "file" so we always have *something*.
    """
    # Strip directory components (defence in depth — werkzeug should
    # already give us just the basename).
    name = os.path.basename(name or "")
    # ASCII-fold via NFKD (é → e, ü → u, …)
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    # Replace runs of unsafe chars with '_'
    name = _UNSAFE_RE.sub("_", name).strip("._")
    if not name:
        name = "file"
    # Cap length to keep on-disk paths sane (sha prefix + name + suffix)
    if len(name) > 200:
        # Keep extension if any
        if "." in name:
            stem, dot, ext = name.rpartition(".")
            stem = stem[: 200 - len(ext) - 1]
            name = f"{stem}.{ext}"
        else:
            name = name[:200]
    return name


def _extension_of(name: str) -> str:
    """Lowercase extension (no dot) of a filename, or '' if none."""
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


# ── Validation ────────────────────────────────────────────────────────


def _validate_extension(filename: str) -> None:
    """Raise AttachmentError if the filename's extension isn't acceptable."""
    from flask_babel import gettext as _

    ext = _extension_of(filename)
    if ext in DENIED_EXTENSIONS:
        raise AttachmentError(
            _("Tipo di file '.%(ext)s' non permesso (potenzialmente eseguibile).", ext=ext)
        )
    if ext not in ALLOWED_EXTENSIONS:
        types = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise AttachmentError(
            _(
                "Tipo di file '.%(ext)s' non supportato. Tipi permessi: %(types)s.",
                ext=ext,
                types=types,
            )
        )


def _validate_entity_type(entity_type: str) -> None:
    from flask_babel import gettext as _

    if entity_type not in ATTACHMENT_ENTITY_TYPES:
        raise AttachmentError(_("entity_type non valido: %(t)s", t=entity_type))


# ── Save / list / delete ──────────────────────────────────────────────


def _hash_and_size(stream: IO[bytes]) -> tuple[str, int, bytes]:
    """Read the entire stream once, returning (sha256_hex, size, blob).

    We need the full blob anyway to compute the sha and write it to
    disk; for our 100 MB ceiling, holding it in memory is fine.
    """
    blob = stream.read()
    sha = hashlib.sha256(blob).hexdigest()
    return sha, len(blob), blob


def save_upload(
    *,
    file: FileStorage,
    entity_type: str,
    entity_id: int,
    uploaded_by_id: int | None,
    caption: str | None = None,
) -> Attachment:
    """Persist an uploaded file: validate, write to disk, insert row.

    Raises:
        AttachmentError: on any validation / IO problem. Caller flashes
        the message and returns to the originating page.
    """
    from flask_babel import gettext as _

    _validate_entity_type(entity_type)

    raw_name = (file.filename or "").strip()
    if not raw_name:
        raise AttachmentError(_("Nessun file selezionato."))

    # Validate extension on the *user-typed* name first (clearer error
    # for the user than after sanitisation).
    _validate_extension(raw_name)

    safe = _safe_filename(raw_name)

    # Read the whole stream — needed for sha + size + write.
    sha, size, blob = _hash_and_size(file.stream)

    if size <= 0:
        raise AttachmentError(_("File vuoto."))

    max_bytes = current_app.config.get("MAX_CONTENT_LENGTH", 100 * 1024 * 1024)
    if size > max_bytes:
        raise AttachmentError(
            _(
                "File troppo grande (%(size).1f MB). Massimo: %(max).0f MB.",
                size=size / (1024 * 1024),
                max=max_bytes / (1024 * 1024),
            )
        )

    storage_filename = f"{sha[:16]}_{safe}"
    target = storage_dir() / storage_filename

    # Dedup: if the file already exists on disk with this storage name,
    # don't rewrite it. (Two rows can legitimately point at the same
    # file, e.g. the same NMR attached to a Run and to a Reaction.)
    if not target.exists():
        try:
            with open(target, "wb") as f:
                f.write(blob)
        except OSError as exc:
            raise AttachmentError(
                _("Errore nel salvataggio del file: %(err)s", err=str(exc))
            ) from exc

    att = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        filename=raw_name[:255],
        storage_filename=storage_filename,
        mime_type=(file.mimetype or None),
        size_bytes=size,
        sha256=sha,
        caption=(caption.strip() if caption else None) or None,
        uploaded_by_id=uploaded_by_id,
    )
    db.session.add(att)
    db.session.commit()
    return att


def list_attachments(entity_type: str, entity_id: int) -> list[Attachment]:
    """All attachments for an entity, oldest first."""
    if entity_type not in ATTACHMENT_ENTITY_TYPES:
        return []
    return (
        db.session.query(Attachment)
        .filter(Attachment.entity_type == entity_type)
        .filter(Attachment.entity_id == entity_id)
        .order_by(Attachment.created_at.asc(), Attachment.id.asc())
        .all()
    )


def count_attachments(entity_type: str, entity_id: int) -> int:
    """Number of attachments on an entity (for badges/counters)."""
    if entity_type not in ATTACHMENT_ENTITY_TYPES:
        return 0
    return (
        db.session.query(Attachment)
        .filter(Attachment.entity_type == entity_type)
        .filter(Attachment.entity_id == entity_id)
        .count()
    )


def delete_attachment(att: Attachment) -> None:
    """Delete the row, plus the on-disk file iff this was the last reference.

    Two rows pointing at the same ``storage_filename`` (dedup case) means
    we must NOT remove the file when only one is deleted.
    """
    storage_filename = att.storage_filename
    db.session.delete(att)
    db.session.flush()  # apply delete before counting refs

    others = (
        db.session.query(Attachment).filter(Attachment.storage_filename == storage_filename).count()
    )
    if others == 0:
        target = storage_dir() / storage_filename
        try:
            if target.exists():
                target.unlink()
        except OSError as exc:
            # Don't roll back the DB delete just because the file is
            # already gone or unwritable — log and move on.
            current_app.logger.warning(
                "Could not remove attachment file %s: %s",
                target,
                exc,
            )

    db.session.commit()
