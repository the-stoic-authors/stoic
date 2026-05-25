"""Stoic ELN — Shopping list (Settimana 6 patch 4).

Builds suggestions for what to (re)order based on the current
inventory state. The suggestion includes:

  - the substance
  - a recommended quantity (threshold + 50% buffer when threshold is set)
  - the supplier of the most recent lot (if any)
  - the catalogue number of the most recent lot
  - an estimated cost from the most recent lot's €/g (or €/mL)
  - a "reason" tag — one of:
      'low_stock'   — current available stock is below threshold
      'empty'       — the substance is at zero (or has no active lot)
      'expiring'    — the only active lot expires within ``expiring_days``
                      (e.g. needs to be replaced before then)

Which categories are included is configurable via three AppSetting
flags:

  - ``shopping.include_low_stock``   (default 'true')
  - ``shopping.include_empty``       (default 'true')
  - ``shopping.include_expiring``    (default 'true')

This way the lab admin can tune what shows up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, func

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.order import OPEN_STATUSES, Order
from stoic_eln.models.settings import AppSetting
from stoic_eln.models.substance import Substance


SETTING_INCLUDE_LOW = "shopping.include_low_stock"
SETTING_INCLUDE_EMPTY = "shopping.include_empty"
SETTING_INCLUDE_EXPIRING = "shopping.include_expiring"


def _flag(key: str, default: bool = True) -> bool:
    """Read a true/false setting from AppSetting."""
    raw = AppSetting.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def get_flags() -> dict:
    """Return current shopping-list flags."""
    return {
        "include_low_stock": _flag(SETTING_INCLUDE_LOW),
        "include_empty": _flag(SETTING_INCLUDE_EMPTY),
        "include_expiring": _flag(SETTING_INCLUDE_EXPIRING),
    }


def set_flags(*, include_low_stock: bool, include_empty: bool, include_expiring: bool) -> None:
    AppSetting.set(SETTING_INCLUDE_LOW, "true" if include_low_stock else "false")
    AppSetting.set(SETTING_INCLUDE_EMPTY, "true" if include_empty else "false")
    AppSetting.set(SETTING_INCLUDE_EXPIRING, "true" if include_expiring else "false")


@dataclass
class ShoppingSuggestion:
    """A single proposed re-order line."""

    substance: Substance
    reason: str  # 'low_stock' | 'empty' | 'expiring'
    suggested_quantity_g: float | None
    suggested_quantity_mL: float | None
    suggested_unit: str  # 'g' or 'mL' or ''
    last_supplier: str | None
    last_catalogue_number: str | None
    last_cost_per_unit: float | None
    estimated_total_cost_eur: float | None
    has_open_order: bool  # already a planned/ordered Order?

    @property
    def reason_label_color(self) -> tuple[str, str]:
        return {
            "low_stock": ("sotto soglia", "info"),
            "empty": ("esaurita", "secondary"),
            "expiring": ("in scadenza", "warning"),
        }.get(self.reason, (self.reason, "secondary"))

    @property
    def suggested_quantity_display(self) -> str:
        if self.suggested_quantity_g is not None:
            return f"{self.suggested_quantity_g:g} g"
        if self.suggested_quantity_mL is not None:
            return f"{self.suggested_quantity_mL:g} mL"
        return "—"


# ── Per-substance helpers ───────────────────────────────────────────────


def _available(item: InventoryItem, today: date) -> bool:
    """A lot 'counts' as stock if it's active, not expired, not empty."""
    if not item.is_active:
        return False
    if item.expiry_date is not None and item.expiry_date < today:
        return False
    cur = item.quantity_g if item.quantity_g is not None else item.quantity_mL
    return cur is not None and cur > 0


def _total_available(sub: Substance, today: date) -> tuple[float, str]:
    """Return (total_qty, unit) where unit is 'g' or 'mL' or ''."""
    g_total = sum(
        (it.quantity_g or 0)
        for it in sub.inventory_items
        if _available(it, today) and it.quantity_g is not None
    )
    mL_total = sum(
        (it.quantity_mL or 0)
        for it in sub.inventory_items
        if _available(it, today) and it.quantity_mL is not None
    )
    if g_total > 0 and mL_total == 0:
        return g_total, "g"
    if mL_total > 0 and g_total == 0:
        return mL_total, "mL"
    if g_total == 0 and mL_total == 0:
        # Default to threshold-driven unit if available
        if sub.low_stock_threshold_g is not None:
            return 0.0, "g"
        if sub.low_stock_threshold_mL is not None:
            return 0.0, "mL"
        return 0.0, ""
    # Both — prefer the unit matching the threshold
    if sub.low_stock_threshold_g is not None:
        return g_total, "g"
    if sub.low_stock_threshold_mL is not None:
        return mL_total, "mL"
    return g_total, "g"


def _most_recent_lot(sub: Substance) -> InventoryItem | None:
    """Return the substance's most recently purchased active lot, if any."""
    lots = [it for it in sub.inventory_items if it.is_active]
    if not lots:
        return None
    # Most recent purchase first; tie-break on created_at
    lots.sort(
        key=lambda it: (it.purchased_at or date.min, it.created_at),
        reverse=True,
    )
    return lots[0]


def _has_open_order(sub: Substance) -> bool:
    """True if there's already a planned/ordered Order for this substance."""
    return (
        db.session.query(Order)
        .filter(Order.substance_id == sub.id)
        .filter(Order.status.in_(OPEN_STATUSES))
        .first()
    ) is not None


# ── Suggestion construction ─────────────────────────────────────────────


def _build_suggestion(
    sub: Substance, reason: str, today: date, *, expiring_days: int = 30
) -> ShoppingSuggestion:
    """Build the suggestion fields for one substance."""
    # Suggested quantity = threshold + 50% buffer (Rico's formula A).
    qty_g: float | None = None
    qty_mL: float | None = None
    unit = ""
    if sub.low_stock_threshold_g is not None and sub.low_stock_threshold_g > 0:
        qty_g = round(sub.low_stock_threshold_g * 1.5, 4)
        unit = "g"
    elif sub.low_stock_threshold_mL is not None and sub.low_stock_threshold_mL > 0:
        qty_mL = round(sub.low_stock_threshold_mL * 1.5, 4)
        unit = "mL"
    else:
        # No threshold (only happens for 'empty' or 'expiring' without threshold).
        # Fall back to the most recent lot's initial quantity, or leave None.
        last = _most_recent_lot(sub)
        if last:
            if last.initial_quantity_g:
                qty_g = last.initial_quantity_g
                unit = "g"
            elif last.initial_quantity_mL:
                qty_mL = last.initial_quantity_mL
                unit = "mL"

    # Supplier and unit cost from the most recent lot
    last = _most_recent_lot(sub)
    supplier = last.supplier if last else None
    catalogue = last.catalogue_number if last else None
    cpu = last.cost_per_unit if last else None
    last_unit = last.cost_per_unit_unit if last else ""

    # Estimated cost — only if our suggested unit matches the last unit cost
    est_cost: float | None = None
    if cpu is not None:
        if last_unit == "/g" and qty_g is not None:
            est_cost = round(cpu * qty_g, 2)
        elif last_unit == "/mL" and qty_mL is not None:
            est_cost = round(cpu * qty_mL, 2)

    return ShoppingSuggestion(
        substance=sub,
        reason=reason,
        suggested_quantity_g=qty_g,
        suggested_quantity_mL=qty_mL,
        suggested_unit=unit,
        last_supplier=supplier,
        last_catalogue_number=catalogue,
        last_cost_per_unit=cpu,
        estimated_total_cost_eur=est_cost,
        has_open_order=_has_open_order(sub),
    )


# ── Public API ──────────────────────────────────────────────────────────


def build_shopping_list(
    *,
    expiring_days: int = 30,
    group_id: int | None = None,
    include_with_open_orders: bool = False,
) -> list[ShoppingSuggestion]:
    """Return a list of ShoppingSuggestion ordered: low-stock, empty, expiring.

    Honours the three include_* flags (in AppSetting). Substances that
    already have an open order (planned or ordered) are EXCLUDED by
    default — once you've planned an order, the suggestion has been
    acted on and shouldn't keep appearing in the shopping list. Pass
    ``include_with_open_orders=True`` to keep them (with
    ``has_open_order=True`` flag) for diagnostics.
    """
    flags = get_flags()
    today = date.today()

    seen_ids: set[int] = set()
    suggestions: list[ShoppingSuggestion] = []

    # --- 1) Low stock ---
    if flags["include_low_stock"]:
        candidates = (
            db.session.query(Substance)
            .filter(Substance.is_active.is_(True))
            .filter(
                or_(
                    Substance.low_stock_threshold_g.isnot(None),
                    Substance.low_stock_threshold_mL.isnot(None),
                )
            )
            .order_by(func.lower(Substance.name).asc())
            .all()
        )
        for sub in candidates:
            if not sub.is_low_stock:
                continue
            total, _u = _total_available(sub, today)
            # Skip "empty with threshold" — they go in the 'empty' bucket
            # only if include_empty is set (and we don't want duplicates).
            if total <= 0:
                continue
            suggestions.append(
                _build_suggestion(sub, "low_stock", today, expiring_days=expiring_days)
            )
            seen_ids.add(sub.id)

    # --- 2) Empty ---
    if flags["include_empty"]:
        # A substance is "empty" if it has at least one inventory record but
        # no available stock (active lots all empty/expired).
        all_subs = (
            db.session.query(Substance)
            .filter(Substance.is_active.is_(True))
            .order_by(func.lower(Substance.name).asc())
            .all()
        )
        for sub in all_subs:
            if sub.id in seen_ids:
                continue
            if not sub.inventory_items:
                continue  # never had a lot → user hasn't really used this
            total, _u = _total_available(sub, today)
            if total <= 0:
                suggestions.append(
                    _build_suggestion(sub, "empty", today, expiring_days=expiring_days)
                )
                seen_ids.add(sub.id)

    # --- 3) Expiring (the *only* available lot expires within window) ---
    if flags["include_expiring"]:
        cutoff = today + timedelta(days=expiring_days)
        all_subs = (
            db.session.query(Substance)
            .filter(Substance.is_active.is_(True))
            .order_by(func.lower(Substance.name).asc())
            .all()
        )
        for sub in all_subs:
            if sub.id in seen_ids:
                continue
            avail = [it for it in sub.inventory_items if _available(it, today)]
            if not avail:
                continue
            # All available lots expire within the window?
            with_exp = [it for it in avail if it.expiry_date is not None]
            if len(with_exp) != len(avail):
                continue  # at least one lot has no expiry → fine
            if all(it.expiry_date <= cutoff for it in with_exp):
                suggestions.append(
                    _build_suggestion(sub, "expiring", today, expiring_days=expiring_days)
                )
                seen_ids.add(sub.id)

    if not include_with_open_orders:
        suggestions = [s for s in suggestions if not s.has_open_order]

    return suggestions
