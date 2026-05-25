"""MixturePrep — record of a single preparation of a Mixture.

Conceptually parallel to ``Run`` (a Reaction execution) but
simplified for the case of preparing a solution / eluent / buffer
from precursor lots: there's no chemistry to track (no equivalents,
no stoichiometry, no yield), only volumetric or mass scaling.

A preparation event:

* targets a specific :class:`Mixture` (the recipe)
* requests a target output quantity (e.g. "10 L of HCl 6N")
* draws from one or more precursor :class:`InventoryItem` lots
  (each consumption tracked as a :class:`MixturePrepConsumption`)
* produces exactly one new :class:`InventoryItem` lot of the target
  mixture, with the auto-generated batch code

The preparation itself runs in a single transaction that:
  1. validates that every precursor lot has enough remaining quantity
  2. decrements ``InventoryItem.quantity_g`` / ``quantity_mL`` on each
     precursor lot by the consumed amount
  3. creates the new lot for the target mixture
  4. inserts the ``MixturePrep`` and ``MixturePrepConsumption`` rows
  5. emits an audit log entry

If anything fails, the whole transaction rolls back — no
half-consumed precursors and no orphan lots.
"""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# Quantity units accepted on the target side. We keep this small and
# explicit because volumetric (mL/L) and mass (g/kg) preparation are
# both common in the lab; conversion between mass and volume is the
# operator's responsibility (the model doesn't try to compute density).
PREP_QUANTITY_UNITS = ("mL", "L", "g", "kg")


class MixturePrep(db.Model):
    """A preparation event: the act of producing one lot of a Mixture
    from precursor lots.
    """

    __tablename__ = "mixture_prep"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Auto-generated batch code (e.g. "HCL6N-2026-001"). Unique
    # across all preps in the lab, same constraint shape as Run.code.
    code: Mapped[str] = mapped_column(
        String(80),
        unique=True,
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # The mixture (recipe) being prepared.
    mixture_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mixture.id"),
        nullable=False,
        index=True,
    )

    # Target quantity the operator asked for. The actual produced
    # quantity is whatever ends up on the output_inventory_item; in
    # practice the two match unless the operator manually overrode
    # the consumption math.
    target_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    target_quantity_unit: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )

    # The lot created by this preparation. One-to-one — each prep
    # creates exactly one new lot. We keep the link bidirectional to
    # make audit queries cheap (find the prep that created a given
    # lot, find the lot produced by a given prep).
    output_inventory_item_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("inventory_item.id"),
        nullable=True,
        index=True,
    )

    prepared_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("user.id"),
        nullable=True,
    )
    prepared_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_now_utc,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_now_utc,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_now_utc,
        onupdate=_now_utc,
    )

    # Relationships
    mixture = relationship(
        "Mixture",
        foreign_keys=[mixture_id],
    )
    output_lot = relationship(
        "InventoryItem",
        foreign_keys=[output_inventory_item_id],
    )
    prepared_by = relationship("User", foreign_keys=[prepared_by_id])

    consumptions: Mapped[list[MixturePrepConsumption]] = relationship(
        "MixturePrepConsumption",
        back_populates="prep",
        cascade="all, delete-orphan",
        order_by="MixturePrepConsumption.position",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MixturePrep id={self.id} code={self.code!r}>"

    # ── Cost properties (Settimana 7 patch 14.6.8) ───────────────
    #
    # Computes how much this preparation cost in raw material,
    # by imputing a fraction of each precursor lot's total_cost
    # proportional to the quantity consumed. Returns None when
    # ANY precursor lot is missing cost or initial quantity data —
    # we don't want to under-report by treating missing data as 0.

    @property
    def total_cost_eur(self) -> float | None:
        """Total imputed material cost of this preparation, in EUR.

        Sum of each consumption's ``imputed_cost_eur``. If any
        consumption can't compute its cost (missing data on the
        lot), the prep's total is None — explicit "unknown"
        beats a silently low number.
        """
        running = 0.0
        for cons in self.consumptions:
            piece = cons.imputed_cost_eur
            if piece is None:
                return None
            running += piece
        return running

    @property
    def cost_per_unit(self) -> float | None:
        """Material cost per gram or mL of the produced lot. Useful
        for pricing or for comparing prep methods.

        Returns None if total_cost is unknown or output_lot is missing
        (e.g. a half-saved prep without a produced lot yet).
        """
        total = self.total_cost_eur
        if total is None or self.output_lot is None:
            return None
        if self.output_lot.initial_quantity_g:
            return total / self.output_lot.initial_quantity_g
        if self.output_lot.initial_quantity_mL:
            return total / self.output_lot.initial_quantity_mL
        return None

    @property
    def cost_per_unit_display(self) -> str:
        cpu = self.cost_per_unit
        if cpu is None:
            return "—"
        # Match output lot's unit category.
        if self.output_lot and self.output_lot.initial_quantity_g:
            return f"€ {cpu:.4f}/g"
        if self.output_lot and self.output_lot.initial_quantity_mL:
            return f"€ {cpu:.4f}/mL"
        return f"€ {cpu:.4f}"


class MixturePrepConsumption(db.Model):
    """One precursor lot consumed by a preparation event."""

    __tablename__ = "mixture_prep_consumption"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    prep_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mixture_prep.id"),
        nullable=False,
        index=True,
    )
    inventory_item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("inventory_item.id"),
        nullable=False,
        index=True,
    )

    quantity_consumed: Mapped[float] = mapped_column(Float, nullable=False)
    quantity_unit: Mapped[str] = mapped_column(String(8), nullable=False)

    # Display order within the prep (= position of the matching
    # MixtureComponent on the recipe). Defaults to 0.
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    prep = relationship(
        "MixturePrep",
        back_populates="consumptions",
    )
    inventory_item = relationship(
        "InventoryItem",
        foreign_keys=[inventory_item_id],
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MixturePrepConsumption id={self.id} "
            f"lot={self.inventory_item_id} "
            f"qty={self.quantity_consumed}{self.quantity_unit}>"
        )

    @property
    def imputed_cost_eur(self) -> float | None:
        """Cost imputed to this consumption, in EUR.

        Equals ``lot.cost_per_unit * quantity_consumed`` after
        normalising the consumed quantity to the same unit
        (g or mL) used by ``cost_per_unit``.

        Returns None if the lot has no cost_per_unit (= no
        cost or no initial quantity recorded), or if the
        consumption unit can't be normalised. The prep's
        ``total_cost_eur`` propagates None upward in that case.
        """
        lot = self.inventory_item
        if lot is None:
            return None
        cpu = lot.cost_per_unit
        if cpu is None:
            return None
        # Normalise: lot tracks initial_quantity in either g or mL.
        # The unit of cost_per_unit matches.
        unit = self.quantity_unit
        qty = self.quantity_consumed
        if unit in ("g",):
            qty_norm = qty
        elif unit in ("kg",):
            qty_norm = qty * 1000.0
        elif unit in ("mL",):
            qty_norm = qty
        elif unit in ("L",):
            qty_norm = qty * 1000.0
        else:
            return None
        # Sanity check: lot's cost_per_unit is per g or per mL.
        # If we consumed mass from a volume-priced lot (or
        # vice versa), we can't compute — the units would mix.
        is_mass_priced = lot.initial_quantity_g is not None and lot.initial_quantity_g > 0
        is_volume_priced = lot.initial_quantity_mL is not None and lot.initial_quantity_mL > 0
        consumed_is_mass = unit in ("g", "kg")
        consumed_is_volume = unit in ("mL", "L")
        if is_mass_priced and consumed_is_volume:
            return None
        if is_volume_priced and consumed_is_mass:
            return None
        return cpu * qty_norm
