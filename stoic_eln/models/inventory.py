"""Stoic ELN — InventoryItem model.

A physical lot of a substance: quantity, cost, location, batch info.
A substance can have many lots (different purchases over time).
"""

from __future__ import annotations

from datetime import date, datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
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
    from stoic_eln.models.mixture import Mixture
    from stoic_eln.models.substance import Substance
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class InventoryItem(db.Model):
    """A specific lot/batch of a substance in the lab inventory."""

    __tablename__ = "inventory_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # An InventoryItem belongs to EITHER a pure Substance or a
    # Mixture (a prepared solution / eluent / buffer). Exactly one
    # of these two FKs must be set — the CHECK constraint defined
    # in ``__table_args__`` enforces this at the database level, and
    # the model adds a Python validator for early failure.
    #
    # Pre-13.0 lots only had ``substance_id`` (and it was NOT NULL).
    # The migration relaxes the NOT NULL on ``substance_id`` and
    # introduces ``mixture_id`` alongside; existing lots automatically
    # remain ``substance_id``-only and continue to work unchanged.
    substance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("substance.id"), nullable=True, index=True
    )
    mixture_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mixture.id"), nullable=True, index=True
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

    # Owner group (Settimana 6). Every lot belongs to a Group — the
    # research team / project that owns the inventory and to which costs
    # are attributed. The migration assigns existing lots to the
    # "Default" group; the column is NOT NULL going forward.
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("group.id"),
        nullable=False,
        index=True,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, onupdate=_now_utc, nullable=False
    )

    # Relationships
    substance: Mapped[Substance | None] = relationship(
        "Substance",
        back_populates="inventory_items",
    )
    mixture: Mapped[Mixture | None] = relationship(
        "Mixture",
        back_populates="inventory_items",
        primaryjoin="InventoryItem.mixture_id == Mixture.id",
    )
    created_by: Mapped[User | None] = relationship("User", foreign_keys=[created_by_id])
    group: Mapped[Group] = relationship("Group", foreign_keys=[group_id])

    # XOR constraint: exactly one of (substance_id, mixture_id) must
    # be set on every row. Using SQLite-compatible boolean arithmetic
    # rather than a SQL XOR keyword (not portable). The expression
    # evaluates to 1 only when one and only one of the two FKs is
    # non-NULL.
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN substance_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN mixture_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_inventory_item_substance_xor_mixture",
        ),
    )

    @property
    def kind(self) -> str:
        """``'substance'`` or ``'mixture'`` — what this lot is a lot of.

        Convenience for templates and reports that need to branch on
        the lot kind without dereferencing the relationships.
        """
        return "mixture" if self.mixture_id is not None else "substance"

    @property
    def display_name(self) -> str:
        """Human label for this lot regardless of substance/mixture.

        Returns the mixture's display label (which already includes
        the primary concentration if set) or the substance's name,
        falling back to a placeholder if both are somehow absent
        (which would violate the CHECK constraint).
        """
        if self.mixture is not None:
            return self.mixture.display_label
        if self.substance is not None:
            return self.substance.name
        return "—"

    def __repr__(self) -> str:
        return f"<InventoryItem #{self.id} batch={self.batch_code!r}>"

    @staticmethod
    def _ensure_group_before_insert(mapper, connection, target):
        """Auto-assign the Default group if group_id is missing.

        This is mostly a convenience for tests and legacy code paths
        that pre-date the group system. Production code should set
        ``group_id`` explicitly to the user's current group.
        """
        if target.group_id is not None:
            return
        # Look up the Default group via the connection (we may not be in
        # a Session-managed flow — e.g. raw inserts in tests).
        from sqlalchemy import text

        row = connection.execute(
            text('SELECT id FROM "group" WHERE slug = :s'), {"s": "default"}
        ).first()
        if row:
            target.group_id = row.id
            return
        # No Default group exists yet — create one inline.
        connection.execute(
            text(
                'INSERT INTO "group" (slug, name, description, '
                "is_default, is_active, created_at) "
                "VALUES ('default', 'Default', "
                "'Gruppo di default del laboratorio.', 1, 1, "
                "CURRENT_TIMESTAMP)"
            )
        )
        row = connection.execute(
            text('SELECT id FROM "group" WHERE slug = :s'), {"s": "default"}
        ).first()
        target.group_id = row.id

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
    def cost_per_unit_unit(self) -> str:
        """The unit string for ``cost_per_unit`` ('/g' or '/mL' or '')."""
        if self.initial_quantity_g and self.initial_quantity_g > 0:
            return "/g"
        if self.initial_quantity_mL and self.initial_quantity_mL > 0:
            return "/mL"
        return ""

    @property
    def cost_per_unit_display(self) -> str:
        cpu = self.cost_per_unit
        if cpu is None:
            return "—"
        return f"€ {cpu:.4f}{self.cost_per_unit_unit}"

    @property
    def cost_per_mole(self) -> float | None:
        """Cost per mole of substance, useful for catalysts and reagents.

        Computes from cost_per_unit + the substance's molecular weight
        (for solids, also requires density to convert mL → g for liquids).
        Returns None if data is missing.
        """
        if self.total_cost_eur is None:
            return None
        sub = self.substance
        if sub is None or not sub.molecular_weight or sub.molecular_weight <= 0:
            return None

        # Compute total moles in the lot.
        if self.initial_quantity_g and self.initial_quantity_g > 0:
            moles = self.initial_quantity_g / sub.molecular_weight
        elif self.initial_quantity_mL and self.initial_quantity_mL > 0:
            if not sub.density or sub.density <= 0:
                return None
            grams = self.initial_quantity_mL * sub.density
            moles = grams / sub.molecular_weight
        else:
            return None

        if moles <= 0:
            return None
        return self.total_cost_eur / moles

    @property
    def percent_remaining(self) -> float | None:
        """Percentage of initial quantity still in stock (0-100)."""
        initial = self.initial_quantity_g or self.initial_quantity_mL
        current = self.quantity_g or self.quantity_mL
        if not initial or initial <= 0 or current is None:
            return None
        return max(0.0, min(100.0, (current / initial) * 100))

    @property
    def is_empty(self) -> bool:
        """True when the lot is fully consumed."""
        cur = self.quantity_g if self.quantity_g is not None else self.quantity_mL
        return cur is not None and cur <= 0

    @property
    def is_expired(self) -> bool:
        """True when ``expiry_date`` is in the past."""
        from datetime import date as _date

        return self.expiry_date is not None and self.expiry_date < _date.today()

    @property
    def is_expiring_soon(self) -> bool:
        """True when ``expiry_date`` is within 30 days from today."""
        from datetime import date as _date, timedelta

        if self.expiry_date is None:
            return False
        soon = _date.today() + timedelta(days=30)
        return _date.today() <= self.expiry_date <= soon

    @property
    def status_key(self) -> str:
        """Categorical status: 'inactive', 'expired', 'empty',
        'expiring', 'in_stock'."""
        if not self.is_active:
            return "inactive"
        if self.is_empty:
            return "empty"
        if self.is_expired:
            return "expired"
        if self.is_expiring_soon:
            return "expiring"
        return "in_stock"

    @property
    def status_label_color(self) -> tuple[str, str]:
        """Return (label_it, bootstrap_color) for the current status."""
        return {
            "inactive": ("inattivo", "secondary"),
            "empty": ("esaurito", "secondary"),
            "expired": ("scaduto", "danger"),
            "expiring": ("in scadenza", "warning"),
            "in_stock": ("in stock", "success"),
        }[self.status_key]

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


# Auto-default group_id on insert if missing (legacy / test convenience)
from sqlalchemy import event as _sa_event  # noqa: E402

_sa_event.listen(
    InventoryItem,
    "before_insert",
    InventoryItem._ensure_group_before_insert,
)
