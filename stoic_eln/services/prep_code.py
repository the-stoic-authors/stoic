"""Stoic ELN — Mixture preparation code formatting.

Generates the human-readable batch code for a mixture preparation
(:class:`MixturePrep`), parallel to ``run_code`` but with a simpler
placeholder set: a mixture preparation has no operator and no
template, just a target mixture, a year, and a sequence number.

Default format:
    prep_code_format = "{mix}-{year}-{seq:03d}"

Where:
  * ``{mix}`` — short slug of the target mixture name
    (uppercased, alphanumeric only). E.g. ``"HCl 6N"`` → ``"HCL6N"``.
    Limited to 16 chars to keep the code printable on labels.
  * ``{year}`` — the current year of the preparation.
  * ``{seq}`` — sequence number; lab-wide by default, scoped to a
    given mixture if you choose ``mix`` scope. Format spec like
    ``{seq:03d}`` is supported via ``str.format``.

Two settings stored in :class:`AppSetting`:

  * ``prep_code_format`` — the format string
  * ``prep_code_scope`` — either ``"lab"`` (sequence shared across
    all preps of the year) or ``"mix"`` (sequence per-mixture, so
    HCl 6N #001, HCl 1N #001, etc.)

The user-facing UI for editing these lives in Settings, alongside
the existing ``run_code_*`` controls.
"""

from __future__ import annotations

import re
from datetime import date

from stoic_eln.extensions import db
from stoic_eln.models.settings import AppSetting

PLACEHOLDERS = ("mix", "year", "seq")
SCOPES = ("lab", "mix")

DEFAULT_FORMAT = "{mix}-{year}-{seq:03d}"
DEFAULT_SCOPE = "lab"

KEY_FORMAT = "prep_code_format"
KEY_SCOPE = "prep_code_scope"

# Validation: format must use only allowed placeholders.
_PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::[^}]*)?\}")

# Slug character allow-list for mixture names: alphanumerics only,
# everything else collapsed. Keep ASCII so the slug is printer-safe.
_SLUG_KEEP_RE = re.compile(r"[^A-Za-z0-9]+")
SLUG_MAX_LEN = 16


def get_format() -> str:
    return AppSetting.get(KEY_FORMAT, DEFAULT_FORMAT) or DEFAULT_FORMAT


def get_scope() -> str:
    return AppSetting.get(KEY_SCOPE, DEFAULT_SCOPE) or DEFAULT_SCOPE


def set_format(fmt: str) -> None:
    """Validate and persist the prep-code format string."""
    validate_format(fmt)
    AppSetting.set(KEY_FORMAT, fmt)


def set_scope(scope: str) -> None:
    if scope not in SCOPES:
        raise ValueError(
            f"Unknown sequence scope {scope!r}. Allowed: {SCOPES}"
        )
    AppSetting.set(KEY_SCOPE, scope)


def validate_format(fmt: str) -> None:
    """Raise ValueError if ``fmt`` is not a usable prep-code template."""
    if not fmt or not fmt.strip():
        raise ValueError("Il formato non può essere vuoto.")
    if fmt.count("{") != fmt.count("}"):
        raise ValueError("Le parentesi graffe non sono bilanciate.")

    used = _PLACEHOLDER_RE.findall(fmt)
    bad = [p for p in used if p not in PLACEHOLDERS]
    if bad:
        raise ValueError(
            f"Placeholder non riconosciuti: {bad}. "
            f"Validi: {PLACEHOLDERS}"
        )
    if "seq" not in used:
        raise ValueError(
            "Il formato deve contenere {seq} per garantire l'unicità."
        )

    # Quick test render to surface any dangling colons / wrong specs.
    try:
        fmt.format(mix="MIX", year=2026, seq=1)
    except (IndexError, KeyError, ValueError) as e:
        raise ValueError(f"Formato non valido: {e}")


def slugify_mixture_name(name: str) -> str:
    """Turn a mixture name into a short alphanumeric token usable in
    a batch code.

    "HCl 6N"            → "HCL6N"
    "HCl 1N"            → "HCL1N"
    "Eluente A 95:5"    → "ELUENTEA955"  (truncated at SLUG_MAX_LEN)
    "Buffer pH 7.4"     → "BUFFERPH74"

    Diacritics are stripped naively (Stoic's mixture names are
    typically ASCII chemistry); for full Unicode handling we'd
    normalize via NFKD first, but that's overkill for this use.
    """
    if not name:
        return "MIX"
    slug = _SLUG_KEEP_RE.sub("", name).upper()
    if not slug:
        return "MIX"
    return slug[:SLUG_MAX_LEN]


def format_prep_code(
    *, fmt: str, mix: str, year: int, seq: int,
) -> str:
    """Render a prep code from explicit values. No DB access."""
    return fmt.format(mix=mix, year=year, seq=seq)


def preview_prep_code(
    *, mix: str = "HCL6N", year: int | None = None,
    seq: int = 1, fmt: str | None = None,
) -> str:
    """Render a sample code for the admin UI."""
    if year is None:
        year = date.today().year
    if fmt is None:
        fmt = get_format()
    try:
        return format_prep_code(fmt=fmt, mix=mix, year=year, seq=seq)
    except (KeyError, IndexError, ValueError):
        return "(formato non valido)"


def next_sequence_number(
    *, scope: str, mixture_id: int, year: int,
) -> int:
    """Compute the next sequence number for a new prep.

    * ``"lab"`` scope: sequence shared across all preps in the year.
    * ``"mix"`` scope: sequence per-mixture (so each mixture has its
      own counter, useful for shops where many lots of the same
      mixture get prepared).
    """
    # Late import to avoid circular dependency at module load time.
    from stoic_eln.models.mixture_prep import MixturePrep

    q = db.session.query(MixturePrep).filter(MixturePrep.year == year)
    if scope == "mix":
        q = q.filter(MixturePrep.mixture_id == mixture_id)
    last = q.order_by(MixturePrep.sequence.desc()).first()
    return (last.sequence + 1) if last else 1


def generate_prep_code(
    *, mixture_name: str, mixture_id: int, year: int | None = None,
) -> tuple[str, int]:
    """End-to-end: read settings, slug the name, compute seq, format.

    Returns ``(code, seq)`` so the caller stores the integer seq
    on the MixturePrep row alongside the rendered code (matches how
    Run does it).
    """
    if year is None:
        year = date.today().year
    fmt = get_format()
    scope = get_scope()
    mix_slug = slugify_mixture_name(mixture_name)
    seq = next_sequence_number(scope=scope, mixture_id=mixture_id, year=year)
    code = format_prep_code(fmt=fmt, mix=mix_slug, year=year, seq=seq)
    return code, seq
