"""Stoic ELN — Step template library ("Procedure").

Reusable workup/extraction/purification procedures that can be
inserted into any reaction protocol. The library is lab-global:
every supervisor sees and uses the same set — standardisation is
the point in a small lab.

Design decision — COPY, not reference: inserting a template into a
reaction COPIES it into regular ReactionStep/ReactionStepComponent/
ChecklistItem rows. Editing the library never rewrites history:
protocols keep the version they were built with (the same snapshot
philosophy Runs apply to reactions). The cost — library updates
don't propagate to existing protocols — is the correct cost for an
ELN, where reproducibility beats convenience.

Templates are created by saving an existing reaction step into the
library ("Salva nella libreria"), not via a dedicated editor: the
full step-editing UI already exists inside protocols, and
duplicating it for the library would double maintenance surface
for no added capability.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db

if TYPE_CHECKING:
    from stoic_eln.models.mixture import Mixture
    from stoic_eln.models.substance import Substance
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class StepTemplate(db.Model):
    """A reusable procedure in the lab-global library."""

    __tablename__ = "step_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    """Unique within the library — saving a step under an existing
    name asks to overwrite."""

    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="workup")
    """Same vocabulary as ReactionStep.kind (STEP_KINDS)."""

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, onupdate=_now_utc, nullable=False
    )

    created_by: Mapped[User | None] = relationship("User", foreign_keys=[created_by_id])

    components: Mapped[list[StepTemplateComponent]] = relationship(
        "StepTemplateComponent",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="StepTemplateComponent.position.asc()",
    )
    checklist_items: Mapped[list[StepTemplateChecklistItem]] = relationship(
        "StepTemplateChecklistItem",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="StepTemplateChecklistItem.position.asc()",
    )

    def __repr__(self) -> str:
        return f"<StepTemplate #{self.id} {self.name!r} kind={self.kind}>"


class StepTemplateComponent(db.Model):
    """Component line of a library procedure — mirrors
    ReactionStepComponent (XOR substance/mixture, ratio_kind)."""

    __tablename__ = "step_template_component"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    template_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("step_template.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    substance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("substance.id"), nullable=True, index=True
    )
    mixture_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mixture.id"), nullable=True, index=True
    )

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="solvent")
    ratio_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="eq")
    ratio_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    concentration_M: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_step_template_component_substance_xor_mixture",
        ),
    )

    template: Mapped[StepTemplate] = relationship("StepTemplate", back_populates="components")
    substance: Mapped[Substance | None] = relationship("Substance", foreign_keys=[substance_id])
    mixture: Mapped[Mixture | None] = relationship("Mixture", foreign_keys=[mixture_id])

    def __repr__(self) -> str:
        return (
            f"<StepTemplateComponent tpl={self.template_id} "
            f"sub={self.substance_id} mix={self.mixture_id}>"
        )


class StepTemplateChecklistItem(db.Model):
    """Checklist line of a library procedure."""

    __tablename__ = "step_template_checklist_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    template_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("step_template.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)

    template: Mapped[StepTemplate] = relationship("StepTemplate", back_populates="checklist_items")

    def __repr__(self) -> str:
        return f"<StepTemplateChecklistItem tpl={self.template_id} {self.text[:30]!r}>"
