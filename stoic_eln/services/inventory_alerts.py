"""Stoic ELN — Inventory alerts (Settimana 6 patch 2).

Computes lists of "things that need attention" from the inventory
state, used by the dashboard and (later) by the shopping list
generator (patch 4).

Three categories:

  - **expired_lots**: lots whose ``expiry_date`` is in the past
  - **expiring_lots**: lots whose ``expiry_date`` is within 30 days
    (upper bound configurable)
  - **low_stock_substances**: substances whose total non-empty
    available stock is below the per-substance threshold
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import or_

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.substance import Substance

if TYPE_CHECKING:
    pass


@dataclass
class InventorySummary:
    """Container for dashboard alert numbers + lists."""

    expired_lots: list[InventoryItem]
    expiring_lots: list[InventoryItem]
    low_stock_substances: list[Substance]
    # Counts for KPI cards
    total_substances: int
    total_active_lots: int
    total_active_lots_value_eur: float
    # Orders (Settimana 6 patch 3)
    open_orders: list = None  # list[Order]
    open_orders_total_eur: float = 0.0

    @property
    def total_alerts(self) -> int:
        return len(self.expired_lots) + len(self.expiring_lots) + len(self.low_stock_substances)


def get_summary(
    *,
    expiring_window_days: int = 30,
    group_id: int | None = None,
) -> InventorySummary:
    """Compute the dashboard summary.

    Args:
        expiring_window_days: how many days ahead to consider as
            "expiring soon". Default 30.
        group_id: if provided, restrict the computation to lots
            belonging to that group. None = all groups.
    """
    today = date.today()
    expiring_cutoff = today + timedelta(days=expiring_window_days)

    base_q = db.session.query(InventoryItem).filter(InventoryItem.is_active.is_(True))
    if group_id is not None:
        base_q = base_q.filter(InventoryItem.group_id == group_id)

    # Expired
    expired_lots = (
        base_q.filter(InventoryItem.expiry_date.isnot(None))
        .filter(InventoryItem.expiry_date < today)
        .filter(
            or_(
                InventoryItem.quantity_g > 0,
                InventoryItem.quantity_mL > 0,
            )
        )
        .join(Substance, InventoryItem.substance_id == Substance.id)
        .order_by(InventoryItem.expiry_date.asc())
        .all()
    )

    # Expiring soon
    expiring_lots = (
        base_q.filter(InventoryItem.expiry_date.isnot(None))
        .filter(InventoryItem.expiry_date >= today)
        .filter(InventoryItem.expiry_date <= expiring_cutoff)
        .filter(
            or_(
                InventoryItem.quantity_g > 0,
                InventoryItem.quantity_mL > 0,
            )
        )
        .join(Substance, InventoryItem.substance_id == Substance.id)
        .order_by(InventoryItem.expiry_date.asc())
        .all()
    )

    # Low stock — fetch all substances with thresholds, filter in-memory
    # because the calculation depends on per-lot expiry/active state.
    candidates = (
        db.session.query(Substance)
        .filter(Substance.is_active.is_(True))
        .filter(
            or_(
                Substance.low_stock_threshold_g.isnot(None),
                Substance.low_stock_threshold_mL.isnot(None),
            )
        )
        .all()
    )
    low_stock_substances = [s for s in candidates if s.is_low_stock]
    low_stock_substances.sort(key=lambda s: s.name)

    # KPIs
    total_substances = db.session.query(Substance).filter(Substance.is_active.is_(True)).count()
    active_lots_q = db.session.query(InventoryItem).filter(InventoryItem.is_active.is_(True))
    if group_id is not None:
        active_lots_q = active_lots_q.filter(InventoryItem.group_id == group_id)
    total_active_lots = active_lots_q.count()
    total_value = sum((lot.total_cost_eur or 0.0) for lot in active_lots_q.all())

    return InventorySummary(
        expired_lots=expired_lots,
        expiring_lots=expiring_lots,
        low_stock_substances=low_stock_substances,
        total_substances=total_substances,
        total_active_lots=total_active_lots,
        total_active_lots_value_eur=total_value,
        open_orders=_open_orders(group_id=group_id),
        open_orders_total_eur=_open_orders_total(group_id=group_id),
    )


def _open_orders(*, group_id: int | None = None):
    """Open orders (planned + ordered) — most overdue first."""
    from stoic_eln.models.order import Order, OPEN_STATUSES

    q = db.session.query(Order).filter(Order.status.in_(OPEN_STATUSES))
    if group_id is not None:
        q = q.filter(Order.group_id == group_id)
    return q.order_by(Order.expected_delivery_date.asc().nulls_last(), Order.created_at.asc()).all()


def _open_orders_total(*, group_id: int | None = None) -> float:
    from stoic_eln.models.order import Order, OPEN_STATUSES

    q = (
        db.session.query(Order)
        .filter(Order.status.in_(OPEN_STATUSES))
        .filter(Order.ordered_total_eur.isnot(None))
    )
    if group_id is not None:
        q = q.filter(Order.group_id == group_id)
    return sum((o.ordered_total_eur or 0.0) for o in q.all())
