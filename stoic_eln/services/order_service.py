"""Stoic ELN — Order service (Settimana 6 patch 3).

Business logic for the order lifecycle:
  - Create a planned order
  - Mark as ordered (placed at supplier)
  - Receive an order (creates an InventoryItem and closes the order)
  - Cancel an order

The Flask routes are thin wrappers around these functions.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.order import (
    STATUS_CANCELLED,
    STATUS_ORDERED,
    STATUS_PLANNED,
    STATUS_RECEIVED,
    STATUS_RECEIVED_PARTIAL,
    Order,
)

if TYPE_CHECKING:
    from stoic_eln.models.user import User


class OrderError(ValueError):
    """Raised on illegal state transition."""


def mark_as_ordered(
    order: Order,
    *,
    ordered_at: date | None = None,
    expected_delivery_date: date | None = None,
    internal_order_ref: str | None = None,
    actor: "User | None" = None,  # noqa: ARG001  (audit hook)
) -> None:
    """Move a 'planned' order to 'ordered'."""
    if order.status != STATUS_PLANNED:
        raise OrderError(
            f"Solo ordini in stato 'pianificato' possono essere segnati "
            f"come ordinati (attuale: {order.status})."
        )
    order.status = STATUS_ORDERED
    order.ordered_at = ordered_at or date.today()
    if expected_delivery_date is not None:
        order.expected_delivery_date = expected_delivery_date
    if internal_order_ref is not None:
        order.internal_order_ref = internal_order_ref
    db.session.flush()


def cancel_order(order: Order, *, reason: str | None = None,
                 actor: "User | None" = None) -> None:  # noqa: ARG001
    """Cancel a planned or ordered order."""
    if order.status not in (STATUS_PLANNED, STATUS_ORDERED):
        raise OrderError(
            f"Non si può annullare un ordine in stato '{order.status}'."
        )
    order.status = STATUS_CANCELLED
    if reason:
        order.notes = (
            (order.notes + "\n\n" if order.notes else "")
            + f"[Annullato] {reason}"
        )
    db.session.flush()


def receive_order(
    order: Order,
    *,
    received_at: date | None = None,
    actual_quantity_g: float | None = None,
    actual_quantity_mL: float | None = None,
    actual_total_eur: float | None = None,
    batch_code: str | None = None,
    expiry_date: date | None = None,
    location: str | None = None,
    notes_extra: str | None = None,
    is_partial: bool = False,
    actor: "User | None" = None,
) -> InventoryItem:
    """Mark an order as received and create the corresponding lot.

    Args:
        order: the order being received.
        received_at: actual delivery date (default today).
        actual_quantity_g/_mL: quantity actually received.
        actual_total_eur: actual cost (might differ from ordered total).
        batch_code: lot/batch code printed on the label.
        expiry_date: lot expiry from supplier.
        location: where in the lab the lot is stored.
        notes_extra: appended to order.notes (e.g. "ricevuto solo 4g
            invece di 5g").
        is_partial: if True, status will be ``received_partial``.

    Returns:
        the freshly-created ``InventoryItem``.

    Raises:
        OrderError if the order is already finalized or quantity is
        not provided.
    """
    if order.status not in (STATUS_PLANNED, STATUS_ORDERED):
        raise OrderError(
            f"Non si può ricevere un ordine in stato '{order.status}'."
        )

    # Prefer actual amount; fall back to ordered amount if unspecified
    qty_g = actual_quantity_g if actual_quantity_g is not None else order.ordered_quantity_g
    qty_mL = actual_quantity_mL if actual_quantity_mL is not None else order.ordered_quantity_mL
    if not (qty_g and qty_g > 0) and not (qty_mL and qty_mL > 0):
        raise OrderError("Quantità ricevuta mancante o nulla.")

    cost = (
        actual_total_eur
        if actual_total_eur is not None
        else order.ordered_total_eur
    )

    rec_at = received_at or date.today()

    # Create the inventory lot
    lot = InventoryItem(
        substance_id=order.substance_id,
        group_id=order.group_id,
        batch_code=batch_code or None,
        supplier=order.supplier,
        catalogue_number=order.catalogue_number,
        quantity_g=qty_g,
        quantity_mL=qty_mL,
        initial_quantity_g=qty_g,
        initial_quantity_mL=qty_mL,
        total_cost_eur=cost,
        purchased_at=rec_at,
        expiry_date=expiry_date,
        location=location,
        is_active=True,
        created_by_id=actor.id if actor else None,
    )
    db.session.add(lot)
    db.session.flush()

    # Update the order
    order.received_at = rec_at
    order.received_quantity_g = qty_g
    order.received_quantity_mL = qty_mL
    order.received_total_eur = cost
    order.inventory_item_id = lot.id
    order.status = STATUS_RECEIVED_PARTIAL if is_partial else STATUS_RECEIVED
    if notes_extra:
        order.notes = (
            (order.notes + "\n\n" if order.notes else "") + notes_extra
        )
    db.session.flush()

    return lot
