"""Stoic ELN — Hazard / precautionary phrase resolution.

Centralised helper for converting code lists (H/P/EUH) into
localised display rows. Handles both atomic codes ("H225",
"P210") and **composed codes** ("P301+P330+P331").

Composed codes are how the EU CLP regulation expresses linked
precautionary statements: a single instruction made of several
fragments that must be read together. For example
``P301+P330+P331`` means

    "IF SWALLOWED: Rinse mouth. Do NOT induce vomiting."

PubChem (and the CLP Annex IV) returns these as a single token,
and rendering them broken into three separate lines loses the
logical link. This service joins the segment texts back together.

Callers pass any mix of atomic and composed codes; the output
list preserves the original order and the composed codes appear
as one row with the joined text.
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models.hazard_phrase import HazardPhrase


def resolve_phrases(codes: list[str], locale: str) -> list[dict]:
    """Look up phrase texts for ``codes`` in the given ``locale``.

    Args:
        codes: list of phrase codes. Each code may be atomic
            (``"H225"``, ``"P210"``, ``"EUH001"``) or a composed
            sequence joined by ``+`` (``"P301+P330+P331"``).
        locale: ``"it"`` or ``"en"``.

    Returns:
        list of ``{"code": <as-provided>, "text": <localised>}``
        dicts, in the same order as the input. For composed codes
        the text is the per-segment text joined by a single space.
        Codes without any stored translation get an empty text.
    """
    if not codes:
        return []

    # Resolve every atomic segment we'll need from the DB.
    atomic_segments: set[str] = set()
    for code in codes:
        for seg in code.split("+"):
            seg = seg.strip()
            if seg:
                atomic_segments.add(seg)

    rows = db.session.query(HazardPhrase).filter(HazardPhrase.code.in_(atomic_segments)).all()
    by_code = {r.code: r for r in rows}

    out: list[dict] = []
    for code in codes:
        segments = [s.strip() for s in code.split("+") if s.strip()]
        if len(segments) == 1:
            phrase = by_code.get(segments[0])
            out.append(
                {
                    "code": code,
                    "text": phrase.text(locale) if phrase else "",
                }
            )
        else:
            # Composed code: P301+P330+P331 → join individual texts.
            # Skip empty fragments so a missing translation doesn't
            # produce a leading/trailing space.
            parts = []
            for seg in segments:
                p = by_code.get(seg)
                if p:
                    parts.append(p.text(locale))
            out.append(
                {
                    "code": code,
                    "text": " ".join(parts),
                }
            )
    return out


def parse_codes(text: str) -> list[str]:
    """Split a comma-separated list of phrase codes into a clean list.

    Each code is uppercased and stripped. Internal ``+`` signs are
    preserved (so ``"H225, P301+P330+P331"`` becomes
    ``["H225", "P301+P330+P331"]``).
    """
    if not text:
        return []
    return [c.strip().upper() for c in text.split(",") if c.strip()]
