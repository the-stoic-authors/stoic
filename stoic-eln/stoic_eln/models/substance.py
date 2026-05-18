"""Stoic ELN — Substance model.

A chemical substance: name, identifiers, physical properties, safety data.
A substance has many inventory items (lots).
"""

from __future__ import annotations

from datetime import datetime, timezone
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
    return datetime.now(timezone.utc).replace(tzinfo=None)


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

    # Notes and metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True
    )
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
        return sum(
            (item.quantity_g or 0) for item in self.inventory_items if item.is_active
        )

    @property
    def total_quantity_mL(self) -> float:
        """Sum of all active inventory items in mL."""
        return sum(
            (item.quantity_mL or 0) for item in self.inventory_items if item.is_active
        )

    @property
    def active_inventory_count(self) -> int:
        return sum(1 for item in self.inventory_items if item.is_active)

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
