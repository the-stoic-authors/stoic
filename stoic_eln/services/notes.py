"""Stoic — Note service (Settimana 6 patch 9)."""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models.note import NOTE_ENTITY_TYPES, Note


def list_notes(entity_type: str, entity_id: int) -> list[Note]:
    """All notes for an entity, oldest first.

    Oldest-first matches conversational order (read top-to-bottom).
    Empty list if none.
    """
    if entity_type not in NOTE_ENTITY_TYPES:
        return []
    return (
        db.session.query(Note)
        .filter(Note.entity_type == entity_type)
        .filter(Note.entity_id == entity_id)
        .order_by(Note.created_at.asc(), Note.id.asc())
        .all()
    )


def count_notes(entity_type: str, entity_id: int) -> int:
    """Number of notes on an entity (for badges/counters)."""
    if entity_type not in NOTE_ENTITY_TYPES:
        return 0
    return (
        db.session.query(Note)
        .filter(Note.entity_type == entity_type)
        .filter(Note.entity_id == entity_id)
        .count()
    )
