"""Stoic ELN — ChecklistItem model.

A single check-list entry attached to either a Reaction (the main reaction
checklist) or to a ReactionStep (the workup/extraction/purification check list).

Exactly one of (reaction_id, step_id) is non-null.

The `is_default_done` flag captures the template-level state: when a Run is
created (Week 4), it will copy the checklist with its own per-run states.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db

if TYPE_CHECKING:
    from stoic_eln.models.reaction import Reaction
    from stoic_eln.models.reaction_step import ReactionStep


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ChecklistItem(db.Model):
    """A single check-list entry — used both at reaction and step level."""

    __tablename__ = "checklist_item"
    __table_args__ = (
        # Exactly one of reaction_id, step_id must be set
        CheckConstraint(
            "(reaction_id IS NOT NULL) <> (step_id IS NOT NULL)",
            name="checklist_item_one_parent",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    reaction_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reaction.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    step_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reaction_step.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    is_default_done: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, nullable=False
    )

    # Relationships are read-only from this side (the parent owns the cascade)
    reaction: Mapped[Reaction | None] = relationship(
        "Reaction",
        foreign_keys=[reaction_id],
        viewonly=True,
        overlaps="checklist_items",
    )
    step: Mapped[ReactionStep | None] = relationship(
        "ReactionStep",
        foreign_keys=[step_id],
        viewonly=True,
        overlaps="checklist_items",
    )

    def __repr__(self) -> str:
        scope = f"r={self.reaction_id}" if self.reaction_id else f"s={self.step_id}"
        return f"<ChecklistItem #{self.id} {scope} {self.text[:30]!r}>"
