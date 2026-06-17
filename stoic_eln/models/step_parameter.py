"""Stoic ELN — StepParameter (P3).

A *recorded process parameter* declared on a reaction step: a labelled
quantity the operator fills in at run time (e.g. distillation pressure,
head temperature). This mirrors the checklist architecture exactly —
the declaration lives here (label + unit, no value), the recorded value
lives on the run side (RunStepParameter.value).

Parameters attach to STEPS only (unlike checklist items, which can also
hang off a reaction as a whole).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db

if TYPE_CHECKING:
    from stoic_eln.models.reaction_step import ReactionStep


class StepParameter(db.Model):
    """A parameter declaration on a reaction step (label + unit)."""

    __tablename__ = "step_parameter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reaction_step.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)

    step: Mapped[ReactionStep] = relationship("ReactionStep", back_populates="parameters")

    def __repr__(self) -> str:
        return f"<StepParameter #{self.id} {self.label!r} ({self.unit})>"
