"""Stoic ELN — Template code validation.

Stoic templates are versioned. The user types a "family" code (the
*base*: e.g. 'MD600B'). When the template is first published, Stoic
appends '.1' to make the actual ``template_code`` ('MD600B.1'). Each
later edit produces a new version ('MD600B.2', '.3', …); the previous
one is archived.

Rules for the BASE code (what the user types):
  - 1 to 8 characters
  - A-Z, 0-9, hyphens (no dots — those are reserved for the version
    suffix appended by Stoic)
  - forced to upper case
  - the FAMILY (base code) must be unique among non-archived templates
"""

from __future__ import annotations

import re

from stoic_eln.extensions import db
from stoic_eln.models.reaction import Reaction

MAX_BASE_LENGTH = 8
MAX_LENGTH = 12  # base (≤8) + '.' + N (up to 999)
_BASE_RE = re.compile(r"^[A-Z0-9-]+$")
_VERSIONED_RE = re.compile(r"^([A-Z0-9-]+)\.(\d+)$")


class TemplateCodeError(ValueError):
    """Raised when a template_code is invalid or already in use."""


def normalize(raw: str | None) -> str:
    """Strip + uppercase. Returns empty string if input is falsy."""
    if not raw:
        return ""
    return raw.strip().upper()


def split_versioned(code: str) -> tuple[str, int] | None:
    """Split 'MD600B.2' into ('MD600B', 2). Returns None if not versioned."""
    m = _VERSIONED_RE.match(code or "")
    if not m:
        return None
    return m.group(1), int(m.group(2))


def make_versioned(base: str, version: int) -> str:
    """Build 'MD600B' + 1 → 'MD600B.1'."""
    return f"{normalize(base)}.{version}"


def validate_base(
    code: str,
    *,
    exclude_id: int | None = None,
) -> str:
    """Validate that ``code`` is a syntactically valid family base, and
    that no OTHER family (any version, archived or not) already exists
    with this base.

    Returns the normalised (upper-cased) base code.
    Raises TemplateCodeError otherwise.
    """
    norm = normalize(code)
    if not norm:
        raise TemplateCodeError("Il codice del template è obbligatorio.")
    if "." in norm:
        raise TemplateCodeError(
            "Il codice del template non può contenere il punto: "
            "il numero di versione viene aggiunto da Stoic automaticamente."
        )
    if len(norm) > MAX_BASE_LENGTH:
        raise TemplateCodeError(
            f"Il codice del template può avere al massimo {MAX_BASE_LENGTH} caratteri."
        )
    if not _BASE_RE.match(norm):
        raise TemplateCodeError(
            "Il codice del template può contenere solo lettere A-Z, cifre 0-9, e trattini."
        )

    # Uniqueness check on the FAMILY: no other published reaction may
    # share this base (except the row identified by exclude_id, which
    # is the current draft itself).
    q = db.session.query(Reaction).filter(
        Reaction.template_code_base == norm,
        Reaction.status == "published",
    )
    if exclude_id is not None:
        q = q.filter(Reaction.id != exclude_id)
    if q.first() is not None:
        raise TemplateCodeError(f"Il codice '{norm}' è già usato da un altro template.")

    return norm


def next_version_for_base(base: str) -> int:
    """Find the next free version number for a given family base.

    Looks at all reactions with ``template_code_base == base`` (regardless
    of status or archived flag) and returns ``max(version_number) + 1``.
    Returns 1 if no reactions exist for this base yet.
    """
    norm = normalize(base)
    last = (
        db.session.query(Reaction)
        .filter(Reaction.template_code_base == norm)
        .order_by(Reaction.version_number.desc())
        .first()
    )
    return (last.version_number + 1) if last else 1


# ─── Legacy API (still used by some routes) ──────────────────────────


def validate(
    code: str,
    *,
    exclude_id: int | None = None,
    allow_replace: bool = False,
) -> str:
    """Legacy: validate a fully-versioned template_code.

    Kept for backwards compat with old code paths. New code should use
    ``validate_base()`` for the family code and let ``promote_draft``
    pick the version suffix.
    """
    norm = normalize(code)
    if not norm:
        raise TemplateCodeError("Il codice del template è obbligatorio.")
    if len(norm) > MAX_LENGTH:
        raise TemplateCodeError(
            f"Il codice del template può avere al massimo {MAX_LENGTH} caratteri."
        )
    # Allow either a base code (no dot) or a versioned code (BASE.N)
    if not (_BASE_RE.match(norm) or _VERSIONED_RE.match(norm)):
        raise TemplateCodeError(
            "Il codice del template può contenere solo lettere A-Z, cifre 0-9, e trattini."
        )

    if allow_replace:
        return norm

    q = db.session.query(Reaction).filter(
        Reaction.template_code == norm,
        Reaction.status == "published",
    )
    if exclude_id is not None:
        q = q.filter(Reaction.id != exclude_id)
    if q.first() is not None:
        raise TemplateCodeError(f"Il codice '{norm}' è già usato da un altro template.")

    return norm
