"""Stoic ELN — RunStep, RunStepComponent, RunChecklistItem.

Snapshots of the template's steps, step components, and checklist items
at the time of run setup. These are independent copies so the run is
robust against later edits to the template.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db

if TYPE_CHECKING:
    from stoic_eln.models.inventory import InventoryItem
    from stoic_eln.models.mixture import Mixture
    from stoic_eln.models.run import Run
    from stoic_eln.models.substance import Substance


class RunStep(db.Model):
    """Snapshot of a ReactionStep, attached to a Run."""

    __tablename__ = "run_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("run.id"), nullable=False, index=True)

    # Snapshot of step metadata
    template_step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    run: Mapped[Run] = relationship("Run", back_populates="steps")
    components: Mapped[list[RunStepComponent]] = relationship(
        "RunStepComponent",
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="RunStepComponent.position",
    )
    checklist_items: Mapped[list[RunChecklistItem]] = relationship(
        "RunChecklistItem",
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="RunChecklistItem.position",
        primaryjoin="and_(RunStep.id==RunChecklistItem.step_id, RunChecklistItem.run_id==None)",
    )

    def __repr__(self) -> str:
        return f"<RunStep #{self.id} title={self.title!r}>"


class RunStepComponent(db.Model):
    """Snapshot of a ReactionStepComponent (workup reagent, solvent,
    eluent). Either substance-backed or mixture-backed (XOR, patch 13.6).
    """

    __tablename__ = "run_step_component"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("run_step.id"), nullable=False, index=True
    )
    substance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("substance.id"), nullable=True, index=True
    )
    mixture_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mixture.id"), nullable=True, index=True
    )
    inventory_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("inventory_item.id"), nullable=True
    )

    free_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    free_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)

    role: Mapped[str] = mapped_column(String(32), nullable=False)
    ratio_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    ratio_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Computed/actual quantities
    target_mass_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_volume_mL: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_mass_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_volume_mL: Mapped[float | None] = mapped_column(Float, nullable=True)

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_run_step_component_substance_xor_mixture",
        ),
    )

    step: Mapped[RunStep] = relationship("RunStep", back_populates="components")
    substance: Mapped[Substance | None] = relationship(
        "Substance",
        foreign_keys=[substance_id],
    )
    mixture: Mapped[Mixture | None] = relationship(
        "Mixture",
        foreign_keys=[mixture_id],
    )
    inventory_item: Mapped[InventoryItem | None] = relationship("InventoryItem")

    def __repr__(self) -> str:
        return f"<RunStepComponent #{self.id} role={self.role!r}>"

    # ── Polymorphic helpers (parallel to RunComponent) ─────────

    @property
    def kind(self) -> str:
        return "mixture" if self.mixture_id is not None else "substance"

    @property
    def display_name(self) -> str:
        if self.mixture is not None:
            return self.mixture.display_label
        if self.substance is not None:
            return self.substance.name
        return "—"

    @property
    def is_free_volume(self) -> bool:
        """True if the template marked this with ratio_kind=='free'.

        Such components have no precomputed target — the operator
        types in the actual volume at run time.
        """
        return self.ratio_kind == "free"


class RunChecklistItem(db.Model):
    """A checklist item attached to a Run (or to one of its steps).

    Mirrors stoic_eln.models.checklist_item.ChecklistItem but lives on
    the run side: each run gets its own copy of the template's checklist
    items, which the operator ticks off during execution.
    """

    __tablename__ = "run_checklist_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # A checklist item is attached EITHER to the run as a whole, OR to
    # a specific step. Exactly one of these is non-null.
    run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("run.id"), nullable=True, index=True
    )
    step_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("run_step.id"), nullable=True, index=True
    )

    text: Mapped[str] = mapped_column(String(500), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Reverse relationships
    run: Mapped[Run | None] = relationship(
        "Run",
        foreign_keys=[run_id],
        backref="checklist_items",
    )
    step: Mapped[RunStep | None] = relationship(
        "RunStep",
        foreign_keys=[step_id],
        back_populates="checklist_items",
        overlaps="checklist_items",
    )

    def __repr__(self) -> str:
        return f"<RunChecklistItem #{self.id} done={self.is_done}>"
