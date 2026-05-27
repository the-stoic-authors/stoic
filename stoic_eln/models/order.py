"""Stoic ELN — Order model.

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

Substance vs Mixture
--------------------
An ``Order`` targets exactly one of:
  - a ``Substance`` (a pure reagent: CuBr₂, EtOAc, pyrrolidine), OR
  - a ``Mixture`` (a commercial preparation: HCl 12N, NaOH 1M, PBS
    pH 7.4 — anything that ships as a multi-component solution).

Exactly one of ``substance_id`` and ``mixture_id`` is set on every
order. The XOR is enforced both by a CHECK constraint at the database
level and by application logic in ``order_service``.

This mirrors the same XOR pattern already in ``InventoryItem``: a lot
in inventory belongs to either a substance or a mixture, and orders
follow the same dichotomy end-to-end.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from flask_babel import lazy_gettext as _l
from sqlalchemy import (
    CheckConstraint,
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
    from stoic_eln.models.mixture import Mixture
    from stoic_eln.models.substance import Substance
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(UTC)


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
    # An Order targets EITHER a pure Substance or a Mixture (a
    # commercial solution / eluent / buffer). Exactly one of the two
    # FKs must be set — the CHECK constraint in ``__table_args__``
    # enforces this at the database level.
    #
    # Pre-Mixture-orders orders only had ``substance_id`` (and it was
    # NOT NULL). The migration relaxes the NOT NULL on ``substance_id``
    # and introduces ``mixture_id`` alongside; existing orders remain
    # ``substance_id``-only and continue to work unchanged.
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
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("group.id"),
        nullable=False,
        index=True,
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
        String(24),
        default=STATUS_PLANNED,
        nullable=False,
        index=True,
    )

    # Free-text notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── If received, link to the resulting lot ────────────────────────
    inventory_item_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("inventory_item.id"),
        nullable=True,
        index=True,
    )

    # ── Audit ─────────────────────────────────────────────────────────
    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("user.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now_utc,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now_utc,
        onupdate=_now_utc,
        nullable=False,
    )

    # ── Constraints ───────────────────────────────────────────────────
    # XOR constraint: exactly one of (substance_id, mixture_id) must be
    # set on every row. Using SQLite-compatible boolean arithmetic
    # rather than a SQL XOR keyword (not portable). Mirrors the same
    # pattern used by InventoryItem.
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_purchase_order_substance_xor_mixture",
        ),
    )

    # ── Relationships ─────────────────────────────────────────────────
    substance: Mapped[Substance | None] = relationship(
        "Substance",
        foreign_keys=[substance_id],
    )
    mixture: Mapped[Mixture | None] = relationship(
        "Mixture",
        foreign_keys=[mixture_id],
    )
    group: Mapped[Group] = relationship("Group")
    inventory_item: Mapped[InventoryItem | None] = relationship(
        "InventoryItem",
        foreign_keys=[inventory_item_id],
    )
    created_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_by_id],
    )

    def __repr__(self) -> str:
        target = (
            f"substance={self.substance_id}"
            if self.substance_id is not None
            else f"mixture={self.mixture_id}"
        )
        return f"<Order #{self.id} {target} {self.ordered_quantity_display} status={self.status}>"

    # ── Convenience properties ────────────────────────────────────────

    @property
    def kind(self) -> str:
        """``'substance'`` or ``'mixture'`` — what this order targets.

        Convenience for templates and routes that need to branch on
        the order kind without dereferencing the relationships.
        """
        return "mixture" if self.mixture_id is not None else "substance"

    @property
    def target_name(self) -> str:
        """Human label for what's being ordered.

        Returns the substance or mixture display label, regardless of
        kind. For Mixture this includes the concentration when set
        (e.g. "HCl 12N (12 N)") so two mixtures with the same name but
        different concentrations are distinguishable in lists and
        dropdowns. Empty string if neither is set (shouldn't happen
        with the XOR constraint, but defensive).
        """
        if self.mixture is not None:
            return self.mixture.display_label
        if self.substance is not None:
            return self.substance.name
        return ""

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
            STATUS_PLANNED: (_l("pianificato"), "secondary"),
            STATUS_ORDERED: (_l("ordinato"), "primary"),
            STATUS_RECEIVED: (_l("ricevuto"), "success"),
            STATUS_RECEIVED_PARTIAL: (_l("ricevuto parziale"), "warning"),
            STATUS_CANCELLED: (_l("annullato"), "secondary"),
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
