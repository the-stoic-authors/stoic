"""Stoic ELN — Substance model.

A chemical substance: name, identifiers, physical properties, safety data.
A substance has many inventory items (lots).
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
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
    from stoic_eln.models.inventory import InventoryItem
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Substance(db.Model):
    """A chemical substance entry in the lab catalogue."""

    __tablename__ = "substance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Names and identifiers
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    iupac_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    cas_number: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    molecular_formula: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    molecular_weight: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Structural identifiers (used for search and duplicate detection)
    smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchi: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchi_key: Mapped[str | None] = mapped_column(
        String(27), nullable=True, unique=True, index=True
    )

    # Physical properties
    density: Mapped[float | None] = mapped_column(Float, nullable=True)  # g/mL
    state: Mapped[str | None] = mapped_column(String(16), nullable=True)  # solid|liquid|gas
    is_solvent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    melting_point_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    boiling_point_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Visualization
    structure_image: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Safety
    ghs_pictograms: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    h_phrases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    p_phrases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Source tracking
    pubchem_cid: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Low-stock thresholds (Settimana 6 patch 2). When the total available
    # quantity (sum of active lots' remaining quantity) falls below this
    # threshold, the substance shows up in the dashboard "low stock" alerts.
    # NULL means no threshold set (no alert). Use _g for solids and _mL
    # for liquids (state-driven; both can be set if the substance can be
    # bought either way).
    low_stock_threshold_g: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    low_stock_threshold_mL: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # Notes and metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, onupdate=_now_utc, nullable=False
    )

    # Soft-delete: keeps historic references intact
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Relationships
    created_by: Mapped[User | None] = relationship("User", foreign_keys=[created_by_id])
    inventory_items: Mapped[list[InventoryItem]] = relationship(
        "InventoryItem",
        back_populates="substance",
        cascade="all, delete-orphan",
        order_by="InventoryItem.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Substance #{self.id} {self.name!r}>"

    @property
    def display_name(self) -> str:
        """Best human label: prefer name, fall back to IUPAC or formula."""
        return self.name or self.iupac_name or self.molecular_formula or f"#{self.id}"

    @property
    def total_quantity_g(self) -> float:
        """Sum of all active inventory items in grams."""
        return sum((item.quantity_g or 0) for item in self.inventory_items if item.is_active)

    @property
    def total_quantity_mL(self) -> float:
        """Sum of all active inventory items in mL."""
        return sum((item.quantity_mL or 0) for item in self.inventory_items if item.is_active)

    @property
    def active_inventory_count(self) -> int:
        return sum(1 for item in self.inventory_items if item.is_active)

    @property
    def is_low_stock(self) -> bool:
        """True if the total non-empty active stock is below the threshold.

        We consider a lot 'available' if it's active AND not empty AND
        not expired. Returns False if no threshold is set.
        """
        from datetime import date as _date

        def _available(item) -> bool:
            if not item.is_active:
                return False
            if item.expiry_date is not None and item.expiry_date < _date.today():
                return False
            cur = item.quantity_g if item.quantity_g is not None else item.quantity_mL
            return cur is not None and cur > 0

        if self.low_stock_threshold_g is not None:
            total = sum(
                (it.quantity_g or 0)
                for it in self.inventory_items
                if _available(it) and it.quantity_g is not None
            )
            if total < self.low_stock_threshold_g:
                return True
        if self.low_stock_threshold_mL is not None:
            total = sum(
                (it.quantity_mL or 0)
                for it in self.inventory_items
                if _available(it) and it.quantity_mL is not None
            )
            if total < self.low_stock_threshold_mL:
                return True
        return False

    @property
    def low_stock_summary(self) -> str | None:
        """Human-readable 'X g remaining (threshold: Y g)' for the dashboard.

        Returns None if no threshold is set.
        """
        from datetime import date as _date

        def _available(item) -> bool:
            if not item.is_active:
                return False
            if item.expiry_date is not None and item.expiry_date < _date.today():
                return False
            cur = item.quantity_g if item.quantity_g is not None else item.quantity_mL
            return cur is not None and cur > 0

        if self.low_stock_threshold_g is not None:
            total = sum(
                (it.quantity_g or 0)
                for it in self.inventory_items
                if _available(it) and it.quantity_g is not None
            )
            return f"{total:g} g (soglia: {self.low_stock_threshold_g:g} g)"
        if self.low_stock_threshold_mL is not None:
            total = sum(
                (it.quantity_mL or 0)
                for it in self.inventory_items
                if _available(it) and it.quantity_mL is not None
            )
            return f"{total:g} mL (soglia: {self.low_stock_threshold_mL:g} mL)"
        return None

    def detect_state(self) -> str | None:
        """Determine physical state at 25°C from MP/BP if not explicitly set.

        Returns "solid" | "liquid" | "gas" or None if undecidable.
        """
        if self.state:
            return self.state

        room_temp = 25.0
        if self.melting_point_c is not None and self.melting_point_c > room_temp:
            return "solid"
        if self.boiling_point_c is not None and self.boiling_point_c < room_temp:
            return "gas"
        if (
            self.melting_point_c is not None
            and self.boiling_point_c is not None
            and self.melting_point_c <= room_temp <= self.boiling_point_c
        ):
            return "liquid"
        return None
