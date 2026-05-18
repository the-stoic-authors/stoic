"""Stoic ELN — Run code formatting.

Generates the human-readable code for a run based on:
  - a format string with placeholders {op}, {tem}, {year}, {seq}
  - a sequence scope: 'lab' | 'op' | 'tem' | 'op_tem'

Example settings (the defaults):
    run_code_format = "{op}-{tem}-{year}-{seq:03d}"
    run_code_scope  = "lab"

  → operator "RX", template "TEM1", year 2026, 3rd run of the year (lab-wide)
    produces the code "RX-TEM1-2026-003"

This module exposes:
  - PLACEHOLDERS / SCOPES — sets of valid values
  - format_run_code(...) — pure function, no DB access
  - generate_run_code(...) — full flow including sequence calculation

The sequence calculation is deferred until Week 4 (when Run model lands);
for now ``generate_run_code`` is callable and tested with explicit seq.
"""

from __future__ import annotations

import re
from datetime import date

from stoic_eln.extensions import db
from stoic_eln.models.settings import AppSetting

PLACEHOLDERS = ("op", "tem", "year", "seq")
SCOPES = ("lab", "op", "tem", "op_tem")

DEFAULT_FORMAT = "{op}-{tem}-{year}-{seq:03d}"
DEFAULT_SCOPE = "lab"

# Settings keys
KEY_FORMAT = "run_code_format"
KEY_SCOPE = "run_code_scope"

# Validation: format must use only allowed placeholders, brace pairs balanced.
_PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def get_format() -> str:
    return AppSetting.get(KEY_FORMAT, DEFAULT_FORMAT) or DEFAULT_FORMAT


def get_scope() -> str:
    return AppSetting.get(KEY_SCOPE, DEFAULT_SCOPE) or DEFAULT_SCOPE


def set_format(fmt: str) -> None:
    """Validate and persist the run-code format string."""
    validate_format(fmt)
    AppSetting.set(KEY_FORMAT, fmt)


def set_scope(scope: str) -> None:
    if scope not in SCOPES:
        raise ValueError(
            f"Unknown sequence scope {scope!r}. Allowed: {SCOPES}"
        )
    AppSetting.set(KEY_SCOPE, scope)


def validate_format(fmt: str) -> None:
    """Raise ValueError if ``fmt`` is not a usable run-code template.

    Constraints:
      - braces must balance
      - all placeholders must be in PLACEHOLDERS
      - {seq} must appear at least once (otherwise the code is not unique)
    """
    if not fmt or not fmt.strip():
        raise ValueError("Il formato non può essere vuoto.")

    # Quick brace-pair check
    if fmt.count("{") != fmt.count("}"):
        raise ValueError("Le parentesi graffe non sono bilanciate.")

    placeholders_used = _PLACEHOLDER_RE.findall(fmt)
    if not placeholders_used:
        raise ValueError(
            "Il formato non contiene placeholder. Usa {op}, {tem}, {year}, {seq}."
        )

    bad = [p for p in placeholders_used if p not in PLACEHOLDERS]
    if bad:
        raise ValueError(
            f"Placeholder non riconosciuti: {bad}. "
            f"Usa solo: {', '.join(PLACEHOLDERS)}."
        )

    if "seq" not in placeholders_used:
        raise ValueError(
            "Il formato deve contenere {seq} per garantire codici unici."
        )

    # Try a dry-run format to catch syntax errors (e.g. invalid format spec)
    try:
        fmt.format(op="OP", tem="TEM", year=2026, seq=1)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"Formato non valido: {e}") from e


def format_run_code(
    *,
    fmt: str,
    op: str,
    tem: str,
    year: int,
    seq: int,
) -> str:
    """Apply a format string to the four placeholders.

    Pure function — no DB access, no defaults. Caller passes everything in.
    Useful for tests and previews.
    """
    return fmt.format(op=op, tem=tem, year=year, seq=seq)


def preview_run_code(
    *, op: str = "RX", tem: str = "TEM1", year: int | None = None,
    seq: int = 1, fmt: str | None = None,
) -> str:
    """Render a sample code for use in the admin UI to preview the format."""
    if year is None:
        year = date.today().year
    if fmt is None:
        fmt = get_format()
    try:
        return format_run_code(fmt=fmt, op=op, tem=tem, year=year, seq=seq)
    except (KeyError, IndexError, ValueError):
        return "(formato non valido)"


def next_sequence_number(
    *,
    scope: str,
    op: str,
    tem: str,
    year: int,
) -> int:
    """Compute the next sequence number for a new run, given the scope.

    Looks at existing Run records (Week 4) filtered by the scope-relevant
    fields. For now the Run model doesn't exist yet, so we return 1 if there
    are no rows. The function is structured so that when the Run model lands
    in Week 4, only the body changes — the signature stays.
    """
    # Avoid import cycles. Run model lands in Week 4.
    try:
        from stoic_eln.models.run import Run  # type: ignore[import-not-found]
    except ImportError:
        # No Run model yet — sequence starts at 1.
        return 1

    q = db.session.query(Run).filter(Run.year == year)
    if scope == "op":
        q = q.filter(Run.operator_code == op)
    elif scope == "tem":
        q = q.filter(Run.template_code == tem)
    elif scope == "op_tem":
        q = q.filter(Run.operator_code == op, Run.template_code == tem)
    # 'lab' scope: no further filter

    # Run model is expected to expose a `sequence` integer column.
    last = q.order_by(Run.sequence.desc()).first()
    return (last.sequence + 1) if last else 1


def generate_run_code(
    *,
    op: str,
    tem: str,
    year: int | None = None,
) -> tuple[str, int]:
    """End-to-end: figure out scope+seq from settings, format, return code+seq.

    Returns ``(code, seq)`` so the caller can store the integer sequence on
    the Run row alongside the rendered code.
    """
    if year is None:
        year = date.today().year
    fmt = get_format()
    scope = get_scope()
    seq = next_sequence_number(scope=scope, op=op, tem=tem, year=year)
    code = format_run_code(fmt=fmt, op=op, tem=tem, year=year, seq=seq)
    return code, seq
