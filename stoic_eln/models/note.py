"""Stoic — Note model (Settimana 6 patch 9).

A user-authored markdown note attached to a Run, Reaction (template),
or Substance. Generic association via (entity_type, entity_id).

Editable by the author (with an updated_at timestamp); deletable
only by admins. Hard delete (no soft-delete) for simplicity — the
audit log preserves the history of create/update/delete.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Allowed entity types. Centralised here so the routes can validate
# user-provided entity_type values against this whitelist.
NOTE_ENTITY_TYPES: tuple[str, ...] = ("run", "reaction", "substance")


class Note(db.Model):
    """A user-authored markdown note attached to a Run/Reaction/Substance."""

    __tablename__ = "note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Generic association: which entity is this note attached to.
    # We don't use a polymorphic base table because the three target
    # tables have wildly different lifecycles and querying them
    # together is rare; a flat (entity_type, entity_id) pair keeps
    # the schema simple and SQLite-friendly.
    entity_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Markdown source. Rendering happens at display time via the
    # services/markdown module so the stored data stays authoritative.
    body: Mapped[str] = mapped_column(Text, nullable=False)

    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, nullable=False, index=True,
    )
    # Set when the author edits an existing note; None means never modified.
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )

    # Relationships
    author = relationship("User", lazy="joined")

    __table_args__ = (
        # Composite index for the common query: "all notes on this entity,
        # newest first" — used by the detail pages.
        Index(
            "ix_note_entity_created",
            "entity_type", "entity_id", "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<Note #{self.id} on {self.entity_type}#{self.entity_id}>"

    @property
    def is_modified(self) -> bool:
        """True if the author has edited the note after creation."""
        return self.updated_at is not None
