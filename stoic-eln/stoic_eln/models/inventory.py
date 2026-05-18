"""Stoic ELN — InventoryItem model.

A physical lot of a substance: quantity, cost, location, batch info.
A substance can have many lots (different purchases over time).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
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
    from stoic_eln.models.substance import Substance
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryItem(db.Model):
    """A specific lot/batch of a substance in the lab inventory."""

    __tablename__ = "inventory_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    substance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("substance.id"), nullable=False, index=True
    )

    # Identification
    batch_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    supplier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    catalogue_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Quantity tracking (separate fields for grams vs mL: a lot is one or the other)
    quantity_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_mL: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_quantity_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_quantity_mL: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cost
    total_cost_eur: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Logistics
    purchased_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    # If this lot was produced in-lab from a run (forward link added in Week 4)
    source_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, onupdate=_now_utc, nullable=False
    )

    # Relationships
    substance: Mapped[Substance] = relationship("Substance", back_populates="inventory_items")
    created_by: Mapped[User | None] = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:
        return f"<InventoryItem #{self.id} batch={self.batch_code!r}>"

    @property
    def quantity_display(self) -> str:
        """Human-readable quantity with units."""
        if self.quantity_g is not None and self.quantity_g > 0:
            return f"{self.quantity_g:g} g"
        if self.quantity_mL is not None and self.quantity_mL > 0:
            return f"{self.quantity_mL:g} mL"
        return "—"

    @property
    def initial_quantity_display(self) -> str:
        if self.initial_quantity_g is not None and self.initial_quantity_g > 0:
            return f"{self.initial_quantity_g:g} g"
        if self.initial_quantity_mL is not None and self.initial_quantity_mL > 0:
            return f"{self.initial_quantity_mL:g} mL"
        return "—"

    @property
    def cost_per_unit(self) -> float | None:
        """Cost per gram or per mL, computed from total_cost / initial quantity.

        Returns None if cost or quantity unknown.
        """
        if self.total_cost_eur is None:
            return None
        if self.initial_quantity_g and self.initial_quantity_g > 0:
            return self.total_cost_eur / self.initial_quantity_g
        if self.initial_quantity_mL and self.initial_quantity_mL > 0:
            return self.total_cost_eur / self.initial_quantity_mL
        return None

    @property
    def cost_per_unit_display(self) -> str:
        cpu = self.cost_per_unit
        if cpu is None:
            return "—"
        if self.initial_quantity_g:
            return f"€ {cpu:.4f}/g"
        return f"€ {cpu:.4f}/mL"

    @property
    def percent_remaining(self) -> float | None:
        """Percentage of initial quantity still in stock (0-100)."""
        initial = self.initial_quantity_g or self.initial_quantity_mL
        current = self.quantity_g or self.quantity_mL
        if not initial or initial <= 0 or current is None:
            return None
        return max(0.0, min(100.0, (current / initial) * 100))

    def use_quantity(self, amount: float, unit: str) -> bool:
        """Deduct ``amount`` of ``unit`` ('g' or 'mL') from this lot.

        Returns True if successful, False if insufficient quantity.
        """
        if unit == "g":
            if self.quantity_g is None or self.quantity_g < amount:
                return False
            self.quantity_g -= amount
        elif unit == "mL":
            if self.quantity_mL is None or self.quantity_mL < amount:
                return False
            self.quantity_mL -= amount
        else:
            raise ValueError(f"Unsupported unit: {unit!r}")
        return True
