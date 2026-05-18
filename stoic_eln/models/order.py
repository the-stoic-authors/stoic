"""Stoic ELN — Order model (Settimana 6 patch 3).

An ``Order`` represents a planned or in-progress purchase of a single
inventory lot. The lifecycle is:

    planned  ──→  ordered  ──→  received          ──→  (final)
                              ↘ received_partial  ──→  (final)
                              ↘ cancelled         ──→  (final)

When the order is "received" or "received_partial", a real
``InventoryItem`` is created (linked via ``inventory_item_id``) and
the order itself becomes a historical record useful for accounting
and supplier statistics.

We model **one order per lot** per Rico's preference: a real-world
purchase order with N reagents = N Stoic ``Order`` records, grouped
by supplier+date if the user wants. This keeps the model and UX
simple at the cost of some redundancy in supplier/date fields.

Partial deliveries (e.g. ordered 5 g, received 4 g) are handled with
the dedicated ``received_partial`` status and a ``notes`` explanation
— no second event, no waiting for the rest. The supplier won't ship
the difference.
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
    from stoic_eln.models.group import Group
    from stoic_eln.models.inventory import InventoryItem
    from stoic_eln.models.substance import Substance
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# Status values for an order
STATUS_PLANNED = "planned"
STATUS_ORDERED = "ordered"
STATUS_RECEIVED = "received"
STATUS_RECEIVED_PARTIAL = "received_partial"
STATUS_CANCELLED = "cancelled"

ALL_STATUSES = (
    STATUS_PLANNED,
    STATUS_ORDERED,
    STATUS_RECEIVED,
    STATUS_RECEIVED_PARTIAL,
    STATUS_CANCELLED,
)
OPEN_STATUSES = (STATUS_PLANNED, STATUS_ORDERED)
FINAL_STATUSES = (STATUS_RECEIVED, STATUS_RECEIVED_PARTIAL, STATUS_CANCELLED)


class Order(db.Model):
    """A planned/in-progress purchase of a single inventory lot."""

    __tablename__ = "purchase_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # ── What's being ordered ──────────────────────────────────────────
    substance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("substance.id"), nullable=False, index=True,
    )
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("group.id"), nullable=False, index=True,
    )

    supplier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    catalogue_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Quantity to order (use either _g for solids or _mL for liquids)
    ordered_quantity_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    ordered_quantity_mL: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Pricing — total is normally what you write on the budget line; per-unit
    # is computed for stats, but can also be entered directly.
    ordered_total_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="EUR", nullable=False)

    # ── Lifecycle dates ───────────────────────────────────────────────
    # When the order was placed at the supplier (after planning phase)
    ordered_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Estimated delivery date (entered when ordering)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Actual delivery date (entered at receipt)
    received_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Quantities actually received (may differ from ordered for partial)
    received_quantity_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    received_quantity_mL: Mapped[float | None] = mapped_column(Float, nullable=True)
    received_total_eur: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Bookkeeping ───────────────────────────────────────────────────
    # Internal/external reference (PO number, request number, ...)
    internal_order_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Status from ALL_STATUSES
    status: Mapped[str] = mapped_column(
        String(24), default=STATUS_PLANNED, nullable=False, index=True,
    )

    # Free-text notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── If received, link to the resulting lot ────────────────────────
    inventory_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("inventory_item.id"), nullable=True, index=True,
    )

    # ── Audit ─────────────────────────────────────────────────────────
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, onupdate=_now_utc, nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────
    substance: Mapped["Substance"] = relationship("Substance")
    group: Mapped["Group"] = relationship("Group")
    inventory_item: Mapped["InventoryItem | None"] = relationship(
        "InventoryItem", foreign_keys=[inventory_item_id],
    )
    created_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[created_by_id],
    )

    def __repr__(self) -> str:
        return (
            f"<Order #{self.id} {self.substance_id} "
            f"{self.ordered_quantity_display} status={self.status}>"
        )

    # ── Convenience properties ────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_final(self) -> bool:
        return self.status in FINAL_STATUSES

    @property
    def is_received(self) -> bool:
        return self.status in (STATUS_RECEIVED, STATUS_RECEIVED_PARTIAL)

    @property
    def ordered_quantity_display(self) -> str:
        """'5 g' or '500 mL' or '—'."""
        if self.ordered_quantity_g is not None:
            return f"{self.ordered_quantity_g:g} g"
        if self.ordered_quantity_mL is not None:
            return f"{self.ordered_quantity_mL:g} mL"
        return "—"

    @property
    def received_quantity_display(self) -> str:
        if self.received_quantity_g is not None:
            return f"{self.received_quantity_g:g} g"
        if self.received_quantity_mL is not None:
            return f"{self.received_quantity_mL:g} mL"
        return "—"

    @property
    def status_label_color(self) -> tuple[str, str]:
        """(label_it, bootstrap_color) for the badge."""
        return {
            STATUS_PLANNED: ("pianificato", "secondary"),
            STATUS_ORDERED: ("ordinato", "primary"),
            STATUS_RECEIVED: ("ricevuto", "success"),
            STATUS_RECEIVED_PARTIAL: ("ricevuto parziale", "warning"),
            STATUS_CANCELLED: ("annullato", "secondary"),
        }.get(self.status, (self.status, "secondary"))

    @property
    def days_until_delivery(self) -> int | None:
        """Days until expected_delivery_date (negative if overdue)."""
        if self.expected_delivery_date is None or not self.is_open:
            return None
        return (self.expected_delivery_date - date.today()).days

    @property
    def is_overdue(self) -> bool:
        """True if open and expected delivery is in the past."""
        d = self.days_until_delivery
        return d is not None and d < 0

    @property
    def cost_per_unit(self) -> float | None:
        """€/g or €/mL based on the ordered quantity and total cost."""
        if self.ordered_total_eur is None:
            return None
        if self.ordered_quantity_g and self.ordered_quantity_g > 0:
            return self.ordered_total_eur / self.ordered_quantity_g
        if self.ordered_quantity_mL and self.ordered_quantity_mL > 0:
            return self.ordered_total_eur / self.ordered_quantity_mL
        return None
