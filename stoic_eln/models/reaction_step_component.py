"""Stoic ELN — ReactionStepComponent model.

A substance OR mixture used in a workup/extraction/purification step.

Mixtures are first-class citizens here just like in the main
ReactionComponent: chromatography eluents (EtOAc/PE 5:2), wash
solutions (brine, 1N HCl), buffers — anything you'd grab as a
prepared bottle rather than a pure chemical. The XOR pattern is
identical to ReactionComponent (patch 13.5).

Quantities are expressed as a ratio relative to a reference component
(typically the limiting reagent of the main reaction), with a
flexible kind. The supported ratio kinds are:

  - "eq"         — equivalents relative to the reference's mmol
                   (e.g. "3 eq of NaCl")
  - "mL_per_g"   — mL per gram of the reference
                   (e.g. "10 mL of water per gram of crude")
  - "mL_per_mmol" — mL per mmol of the reference
                   (e.g. "20 mL of EtOAc per mmol of starting material")
  - "percent_vv" — % volume relative to the reference's volume
                   (e.g. "5 % v/v of TFA")
  - "absolute_mL" — fixed volume in mL, no ratio
                   (e.g. "30 mL of brine")
  - "absolute_g"  — fixed mass in grams, no ratio
  - "free"       — quantity NOT specified in the template;
                   the operator records the actual amount at run
                   time. The canonical use case is chromatography
                   eluent: you don't know in advance how many mL
                   of column you'll need.

The actual value is in ``ratio_value`` (omitted for ``free``) and the
unit is ``ratio_kind``.
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
from stoic_eln.models.reaction_component import ROLE_LABELS_IT

if TYPE_CHECKING:
    from stoic_eln.models.mixture import Mixture
    from stoic_eln.models.reaction_step import ReactionStep
    from stoic_eln.models.substance import Substance


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


RATIO_KINDS: tuple[str, ...] = (
    "eq",
    "mL_per_g",
    "mL_per_mmol",
    "percent_vv",
    "absolute_mL",
    "absolute_g",
    "column_diameter_mm",
    "fixed_value",
    "free",
)

RATIO_KIND_LABELS_IT = {
    "eq": "eq",
    "mL_per_g": "mL/g",
    "mL_per_mmol": "mL/mmol",
    "percent_vv": "% v/v",
    "absolute_mL": "mL fissi",
    "absolute_g": "g fissi",
    "column_diameter_mm": "Ø colonna (h letto, cm)",
    "fixed_value": "valore fisso",
    "free": "quanto basta",
}

RATIO_KIND_LABELS_EN = {
    "eq": "eq",
    "mL_per_g": "mL/g",
    "mL_per_mmol": "mL/mmol",
    "percent_vv": "% v/v",
    "absolute_mL": "fixed mL",
    "absolute_g": "fixed g",
    "column_diameter_mm": "column Ø (bed h, cm)",
    "fixed_value": "fixed value",
    "free": "ad lib.",
}


class ReactionStepComponent(db.Model):
    """A component used in a workup/extraction/purification step."""

    __tablename__ = "reaction_step_component"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    step_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reaction_step.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # XOR: exactly one of substance_id / mixture_id is set.
    substance_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("substance.id"),
        nullable=True,
        index=True,
    )
    mixture_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("mixture.id"),
        nullable=True,
        index=True,
    )

    # Free entry (P2): a non-inventory line like "Column diameter" or
    # "Celite pad". Mutually exclusive with substance/mixture. free_unit
    # is an uninterpreted label ("mm", "cm", "CV", ...).
    free_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    free_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="solvent")
    """One of COMPONENT_ROLES (re-using the reaction component roles)."""

    ratio_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="eq")
    """One of RATIO_KINDS — see module docstring."""

    ratio_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    concentration_M: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN free_name IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_reaction_step_component_substance_xor_mixture",
        ),
    )

    # Relationships
    step: Mapped[ReactionStep] = relationship("ReactionStep", back_populates="components")
    substance: Mapped[Substance | None] = relationship(
        "Substance",
        foreign_keys=[substance_id],
    )
    mixture: Mapped[Mixture | None] = relationship(
        "Mixture",
        foreign_keys=[mixture_id],
    )

    def __repr__(self) -> str:
        return (
            f"<ReactionStepComponent step={self.step_id} "
            f"sub={self.substance_id} mix={self.mixture_id} "
            f"{self.ratio_value}{self.ratio_kind}>"
        )

    # ── Polymorphic helpers ─────────────────────────────────────

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
        """True if quantity is not specified at template time.

        The operator records the actual volume at Run time. Typical
        use case: chromatography eluent.
        """
        return self.ratio_kind == "free"

    @property
    def ratio_kind_label(self) -> str:
        return RATIO_KIND_LABELS_IT.get(self.ratio_kind, self.ratio_kind)

    @property
    def role_label_it(self) -> str:
        return ROLE_LABELS_IT.get(self.role, self.role)
