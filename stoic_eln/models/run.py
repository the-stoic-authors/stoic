"""Stoic ELN — Run model.

A Run is a single execution of a reaction template. Lifecycle:

  draft        → operator chose lots, calculated targets visible,
                 can also pre-fill the first checklist
  in_progress  → operator pressed "Avvia esecuzione": real weights are
                 frozen, inventory has been deducted; checklist becomes
                 the live execution log
  completed    → operator pressed "Completa run": yield input, run
                 becomes immutable except for additive notes

A run is essentially a snapshot of a reaction template at a point in
time, with bound inventory lots and actual measured quantities.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db

if TYPE_CHECKING:
    from stoic_eln.models.reaction import Reaction
    from stoic_eln.models.run_component import RunComponent
    from stoic_eln.models.run_step import RunStep
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Run lifecycle states
STATUS_DRAFT = "draft"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
ALL_STATUSES = (STATUS_DRAFT, STATUS_IN_PROGRESS, STATUS_COMPLETED)


class Run(db.Model):
    """A single execution of a reaction template."""

    __tablename__ = "run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Identification
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)

    # Sequence components — needed by run_code service to find the next
    # sequence number under a given scope ("lab" / "op" / "tem" / "op_tem").
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    operator_code: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    template_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    # Link to the template at the time of execution. We keep a hard
    # FK so we can navigate "show me all runs of this template", but
    # we ALSO snapshot the template's display code as a string so the
    # run record stays meaningful even if the template is later
    # deleted/renamed.
    reaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reaction.id"), nullable=False, index=True
    )
    template_code_snapshot: Mapped[str | None] = mapped_column(String(40), nullable=True)
    template_title_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Execution state
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_DRAFT, index=True
    )

    # Stoichiometry: scale chosen by operator at setup
    # The "scale" is the absolute mmol of the limiting reagent for this
    # specific run. All other component target masses/volumes derive
    # from this via the template's equivalents.
    scale_mmol: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Original unit chosen by the operator + raw value. Stored only so
    # the UI can re-display the input the way it was entered (e.g. show
    # "500 mg" instead of "2.5 mmol").
    scale_input_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    scale_input_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Yield (only populated at completion)
    yield_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    yield_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Free-form fields
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Post-mortem additive notes (writable AFTER completion)
    post_completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Dates
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Audit
    operator_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, onupdate=_now_utc, nullable=False
    )

    # Relationships
    reaction: Mapped[Reaction] = relationship("Reaction", back_populates="runs")
    operator: Mapped[User | None] = relationship("User", foreign_keys=[operator_id])
    components: Mapped[list[RunComponent]] = relationship(
        "RunComponent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunComponent.position",
    )
    steps: Mapped[list[RunStep]] = relationship(
        "RunStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunStep.position",
    )

    def __repr__(self) -> str:
        return f"<Run {self.code!r} status={self.status}>"

    # ── Lifecycle helpers ─────────────────────────────────────────────
    @property
    def is_draft(self) -> bool:
        return self.status == STATUS_DRAFT

    @property
    def is_in_progress(self) -> bool:
        return self.status == STATUS_IN_PROGRESS

    @property
    def is_completed(self) -> bool:
        return self.status == STATUS_COMPLETED

    @property
    def is_immutable(self) -> bool:
        """Once completed, only post_completion_notes can be appended."""
        return self.status == STATUS_COMPLETED

    @property
    def status_label_it(self) -> str:
        return {
            STATUS_DRAFT: "in preparazione",
            STATUS_IN_PROGRESS: "in esecuzione",
            STATUS_COMPLETED: "completato",
        }.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        """Bootstrap badge color for the status."""
        return {
            STATUS_DRAFT: "secondary",
            STATUS_IN_PROGRESS: "primary",
            STATUS_COMPLETED: "success",
        }.get(self.status, "secondary")

    @property
    def products(self) -> list:
        """Return the components that are products or byproducts."""
        return [c for c in self.components if c.role in ("product", "byproduct")]

    @property
    def is_failed(self) -> bool:
        """A completed run with no product mass anywhere is treated as 'failed'."""
        if not self.is_completed:
            return False
        if not self.products:
            return False
        # If at least one product has actual_mass_g > 0, not failed.
        for p in self.products:
            if p.actual_mass_g and p.actual_mass_g > 0:
                return False
        # Also accept legacy yield_g if no product-component mass is set
        if self.yield_g and self.yield_g > 0:
            return False
        return True
