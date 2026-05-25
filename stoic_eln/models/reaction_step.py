"""Stoic ELN — ReactionStep model.

A discrete stage of a reaction protocol *after* the main chemistry: workup,
extraction, purification, analysis, etc. Each step has its own description,
its own components (with quantities calculated relative to a chosen reference),
and its own checklist.

The reference is either the limiting reagent of the main reaction (default)
or any specific component the chemist picks.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db

if TYPE_CHECKING:
    from stoic_eln.models.checklist_item import ChecklistItem
    from stoic_eln.models.reaction import Reaction
    from stoic_eln.models.reaction_component import ReactionComponent
    from stoic_eln.models.reaction_step_component import ReactionStepComponent


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# Allowed step kinds — drives the badge color in the UI
STEP_KINDS: tuple[str, ...] = (
    "workup",
    "extraction",
    "purification",
    "analysis",
    "other",
)

STEP_KIND_LABELS_IT = {
    "workup": "Workup",
    "extraction": "Estrazione",
    "purification": "Purificazione",
    "analysis": "Analisi",
    "other": "Altro",
}

STEP_KIND_LABELS_EN = {
    "workup": "Work-up",
    "extraction": "Extraction",
    "purification": "Purification",
    "analysis": "Analysis",
    "other": "Other",
}


class ReactionStep(db.Model):
    """A post-reaction stage: workup, extraction, purification, etc."""

    __tablename__ = "reaction_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    reaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reaction.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="workup")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reference for ratio calculations.
    # If NULL → use the reaction's limiting reagent.
    # Otherwise → use the specific ReactionComponent referenced.
    reference_component_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("reaction_component.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)

    # Relationships
    reaction: Mapped[Reaction] = relationship(
        "Reaction", back_populates="steps", foreign_keys=[reaction_id]
    )
    reference_component: Mapped[ReactionComponent | None] = relationship(
        "ReactionComponent", foreign_keys=[reference_component_id]
    )
    components: Mapped[list[ReactionStepComponent]] = relationship(
        "ReactionStepComponent",
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="ReactionStepComponent.position.asc()",
    )
    checklist_items: Mapped[list[ChecklistItem]] = relationship(
        "ChecklistItem",
        primaryjoin=("ChecklistItem.step_id == ReactionStep.id"),
        cascade="all, delete-orphan",
        order_by="ChecklistItem.position.asc()",
        overlaps="reaction,step",
    )

    def __repr__(self) -> str:
        return f"<ReactionStep #{self.id} kind={self.kind} {self.title!r}>"

    @property
    def kind_label_it(self) -> str:
        return STEP_KIND_LABELS_IT.get(self.kind, self.kind)

    @property
    def kind_label_en(self) -> str:
        return STEP_KIND_LABELS_EN.get(self.kind, self.kind)

    def kind_label(self, locale: str = "it") -> str:
        if locale == "en":
            return self.kind_label_en
        return self.kind_label_it
