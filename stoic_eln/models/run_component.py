"""Stoic ELN — RunComponent model.

A snapshot of one component of a reaction template, bound to a
specific inventory lot AND with a target and an actual measured
amount. A component points at either a pure Substance (most common)
or a Mixture (e.g. HCl 1N used as a reagent — patch 13.5).

For the limiting reagent, target_mass_g is computed from
``run.scale_mmol * substance.molecular_weight``. For all others,
the target derives from equivalents and the limiting reagent's mmol.
For solvents and for mixture-backed components, target is computed
from the concentration and required moles.

The ``actual_mass_g`` and ``actual_volume_mL`` fields are populated
by the operator after physically weighing/measuring. At the moment
the run transitions from draft → in_progress, these actual values
are deducted from the bound inventory lot (which may be a substance
lot or a mixture lot).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db

if TYPE_CHECKING:
    from stoic_eln.models.inventory import InventoryItem
    from stoic_eln.models.mixture import Mixture
    from stoic_eln.models.reaction_component import ReactionComponent
    from stoic_eln.models.run import Run
    from stoic_eln.models.substance import Substance


class RunComponent(db.Model):
    """A single component of a Run, bound to an inventory lot."""

    __tablename__ = "run_component"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("run.id"), nullable=False, index=True)

    template_component_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reaction_component.id"), nullable=True
    )

    # Substance OR Mixture — exactly one is set (XOR check below).
    substance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("substance.id"), nullable=True, index=True
    )
    mixture_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mixture.id"), nullable=True, index=True
    )

    # The chosen lot. Required for non-products before the run can
    # start; products may have it filled in after-the-fact. The lot's
    # own kind (substance lot vs mixture lot) must match this row's
    # kind — validated at run-setup time (not as a DB constraint
    # because it would require a triple-join).
    inventory_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("inventory_item.id"), nullable=True, index=True
    )

    # Snapshot of recipe data (so changes to template don't break the run)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_limiting: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Frozen snapshot of ReactionComponent.track_in_inventory: whether a
    # product/byproduct creates an inventory lot on run completion.
    track_in_inventory: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="1"
    )
    equivalents: Mapped[float | None] = mapped_column(Float, nullable=True)
    concentration_M: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Computed targets at setup (from scale + equivalents/concentration)
    target_mass_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_volume_mL: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Actual measurements by operator
    actual_mass_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_volume_mL: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Visual ordering
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_run_component_substance_xor_mixture",
        ),
    )

    # Relationships
    run: Mapped[Run] = relationship("Run", back_populates="components")
    substance: Mapped[Substance | None] = relationship(
        "Substance",
        foreign_keys=[substance_id],
    )
    mixture: Mapped[Mixture | None] = relationship(
        "Mixture",
        foreign_keys=[mixture_id],
    )
    inventory_item: Mapped[InventoryItem | None] = relationship("InventoryItem")
    template_component: Mapped[ReactionComponent | None] = relationship(
        "ReactionComponent", foreign_keys=[template_component_id]
    )

    def __repr__(self) -> str:
        return f"<RunComponent #{self.id} role={self.role!r}>"

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
    def effective_substance(self) -> Substance | None:
        """The Substance whose MW drives mass/mol math.

        For substance-backed components, that's ``self.substance``.
        For mixture-backed components, it's the primary solute of
        the mixture (first solute MixtureComponent with substance set).
        Returns None if it can't be determined.
        """
        if self.substance is not None:
            return self.substance
        if self.mixture is not None:
            for c in self.mixture.components:
                if c.role == "solute" and c.substance is not None:
                    return c.substance
        return None

    @property
    def is_product(self) -> bool:
        return self.role in ("product", "byproduct")

    @property
    def is_solvent(self) -> bool:
        return self.role == "solvent"

    @property
    def needs_lot(self) -> bool:
        """Non-products MUST have a lot before the run can start."""
        return not self.is_product

    @property
    def actual_amount_unit(self) -> str | None:
        """Returns 'g' or 'mL' depending on which actual amount is set."""
        if self.actual_mass_g is not None:
            return "g"
        if self.actual_volume_mL is not None:
            return "mL"
        return None

    @property
    def actual_amount(self) -> float | None:
        """Returns the actual amount in the unit returned by actual_amount_unit."""
        if self.actual_mass_g is not None:
            return self.actual_mass_g
        if self.actual_volume_mL is not None:
            return self.actual_volume_mL
        return None

    @property
    def target_amount_unit(self) -> str | None:
        if self.target_mass_g is not None:
            return "g"
        if self.target_volume_mL is not None:
            return "mL"
        return None

    @property
    def target_amount(self) -> float | None:
        if self.target_mass_g is not None:
            return self.target_mass_g
        if self.target_volume_mL is not None:
            return self.target_volume_mL
        return None
