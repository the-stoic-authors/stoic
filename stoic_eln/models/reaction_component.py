"""Stoic ELN — ReactionComponent model.

Links a Reaction to either a Substance (pure molecule) or a Mixture
(prepared solution like HCl 1N), with a role (SM, reagent, catalyst, …)
and stoichiometric data. Quantities can be expressed as equivalents,
mmol, g, or mL; the autocalculator keeps them consistent based on the
substance's MW and density.

XOR rule (parallel to InventoryItem): a ReactionComponent has exactly
one of (substance_id, mixture_id) set. When pointing at a Mixture,
the component represents the solute in that mixture — so adding
"HCl 1N, 5 mL" to a reaction means "5 mmol HCl" stoichiometrically.
The active ingredient (Mixture solute → underlying Substance) is
exposed by the ``effective_substance`` property and used in
auto-mol calculations.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
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
    from stoic_eln.models.reaction import Reaction
    from stoic_eln.models.substance import Substance


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# Allowed component roles (validated at form/route level)
COMPONENT_ROLES: tuple[str, ...] = (
    "starting_material",
    "reactant",
    "reagent",
    "catalyst",
    "ligand",
    "base",
    "acid",
    "oxidant",
    "reductant",
    "solvent",
    "stationary_phase",
    "additive",
    "internal_standard",
    "product",
    "byproduct",
)


class ReactionComponent(db.Model):
    """A substance OR mixture used in a reaction, with its role and stoichiometry."""

    __tablename__ = "reaction_component"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    reaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reaction.id"), nullable=False, index=True
    )
    # XOR with mixture_id (CHECK constraint below).
    # Pre-13.5 components only had substance_id NOT NULL; the migration
    # relaxes nullability so a component pointing at a Mixture can
    # leave this NULL.
    substance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("substance.id"), nullable=True, index=True
    )
    mixture_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mixture.id"), nullable=True, index=True
    )

    role: Mapped[str] = mapped_column(String(40), nullable=False, default="reactant")
    """One of COMPONENT_ROLES."""

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Display order within the reaction."""

    # Stoichiometry — at least one of these is provided; the others can be derived
    equivalents: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_mmol: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_mL: Mapped[float | None] = mapped_column(Float, nullable=True)

    # The "limiting reagent": equivalents=1.0 by convention. Only one per reaction.
    is_limiting: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Concentration (for solvents & solutions). For mixture-backed
    # components, the canonical concentration lives on the Mixture
    # itself (primary_concentration / per-component); this field
    # remains for legacy data and for substance-backed components
    # that are themselves solutions (rare but possible).
    concentration_M: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Per-component notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)

    # XOR check (parallel to inventory_item)
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_reaction_component_substance_xor_mixture",
        ),
    )

    # Relationships
    reaction: Mapped[Reaction] = relationship("Reaction", back_populates="components")
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
            f"<ReactionComponent rxn={self.reaction_id} "
            f"sub={self.substance_id} mix={self.mixture_id} "
            f"role={self.role}>"
        )

    # ── Polymorphic helpers ─────────────────────────────────────

    @property
    def kind(self) -> str:
        """``'substance'`` or ``'mixture'`` — what this component is.

        Useful in templates that branch on the component kind without
        dereferencing the relationships.
        """
        return "mixture" if self.mixture_id is not None else "substance"

    @property
    def display_name(self) -> str:
        """Human label regardless of the underlying entity.

        For a mixture, returns ``mixture.display_label`` (which
        already folds in the primary concentration when set,
        e.g. "HCl 1N (1 N)"). For a substance, returns the name.
        """
        if self.mixture is not None:
            return self.mixture.display_label
        if self.substance is not None:
            return self.substance.name
        return "—"

    @property
    def effective_substance(self) -> Substance | None:
        """The active-ingredient substance for stoichiometry.

        For a substance-backed component, that's the substance itself.
        For a mixture-backed component, we pick the *primary solute*
        of the mixture (the one in the first component with role
        ``solute`` whose substance is set). This is what the molarity
        and MW come from when we compute moles from volume.

        Returns ``None`` if neither can be resolved — caller should
        treat as "no auto-mol math possible".
        """
        if self.substance is not None:
            return self.substance
        if self.mixture is not None:
            for c in self.mixture.components:
                if c.role == "solute" and c.substance is not None:
                    return c.substance
        return None

    @property
    def effective_concentration_unit(self) -> str | None:
        """Concentration unit for auto-mol math.

        For a mixture-backed component, returns the mixture's
        ``primary_concentration_unit`` if set, falling back to the
        unit of the primary solute MixtureComponent. ``None`` for
        substance-backed components (which compute moles from
        mass+MW, not concentration+volume).
        """
        if self.mixture is None:
            return None
        if self.mixture.primary_concentration_unit:
            return self.mixture.primary_concentration_unit
        for c in self.mixture.components:
            if c.role == "solute" and c.concentration_unit:
                return c.concentration_unit
        return None

    @property
    def effective_concentration(self) -> float | None:
        """Numeric concentration to use with ``effective_concentration_unit``.

        Mirrors ``effective_concentration_unit`` selection logic.
        """
        if self.mixture is None:
            return None
        if self.mixture.primary_concentration is not None:
            return self.mixture.primary_concentration
        for c in self.mixture.components:
            if c.role == "solute" and c.concentration is not None:
                return c.concentration
        return None

    @property
    def amount_display(self) -> str:
        if self.amount_g is not None and self.amount_g > 0:
            return f"{self.amount_g:.4g} g"
        if self.amount_mL is not None and self.amount_mL > 0:
            return f"{self.amount_mL:.4g} mL"
        return "—"

    @property
    def role_label_it(self) -> str:
        return ROLE_LABELS_IT.get(self.role, self.role)


ROLE_LABELS_IT = {
    "starting_material": "SM",
    "reactant": "reattivo",
    "reagent": "reagente",
    "catalyst": "catalizzatore",
    "ligand": "legante",
    "base": "base",
    "acid": "acido",
    "oxidant": "ossidante",
    "reductant": "riducente",
    "solvent": "solvente",
    "stationary_phase": "fase stazionaria",
    "additive": "additivo",
    "internal_standard": "std interno",
    "product": "prodotto",
    "byproduct": "sottoprodotto",
}

ROLE_LABELS_EN = {
    "starting_material": "SM",
    "reactant": "reactant",
    "reagent": "reagent",
    "catalyst": "catalyst",
    "ligand": "ligand",
    "base": "base",
    "acid": "acid",
    "oxidant": "oxidant",
    "reductant": "reductant",
    "solvent": "solvent",
    "stationary_phase": "stationary phase",
    "additive": "additive",
    "internal_standard": "int. std",
    "product": "product",
    "byproduct": "byproduct",
}
