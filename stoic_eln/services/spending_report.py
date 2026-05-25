"""Spending report: aggregate purchase costs into time buckets.

Source of data: ``InventoryItem.total_cost_eur`` indexed by
``InventoryItem.purchased_at``. A lot with no ``purchased_at`` or
no ``total_cost_eur`` is silently skipped — partial data shouldn't
break the report.

The bucketing key is built in Python from ``purchased_at`` (a date)
rather than via a DB-specific function, so the report works the
same on SQLite (dev) and Postgres (future). Costs do not need to be
huge; the bottleneck is ergonomic, not performance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem


# ── Bucket helpers ───────────────────────────────────────────────


def _week_bucket_key(d: date) -> str:
    """ISO week key like '2026-W21' — Monday-anchored, locale-stable."""
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _week_bucket_label(d: date) -> str:
    """Human label like 'Lun 18 mag — Dom 24 mag 2026'."""
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    # Italian month abbreviations to match the rest of the UI.
    months_it = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
    if monday.year == sunday.year:
        return (
            f"{monday.day} {months_it[monday.month - 1]} – "
            f"{sunday.day} {months_it[sunday.month - 1]} {sunday.year}"
        )
    return (
        f"{monday.day} {months_it[monday.month - 1]} {monday.year} – "
        f"{sunday.day} {months_it[sunday.month - 1]} {sunday.year}"
    )


def _month_bucket_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _month_bucket_label(d: date) -> str:
    months_it = [
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
    ]
    return f"{months_it[d.month - 1]} {d.year}"


def _quarter_bucket_key(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def _quarter_bucket_label(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"


def _year_bucket_key(d: date) -> str:
    return str(d.year)


def _year_bucket_label(d: date) -> str:
    return str(d.year)


_BUCKETERS = {
    "week": (_week_bucket_key, _week_bucket_label),
    "month": (_month_bucket_key, _month_bucket_label),
    "quarter": (_quarter_bucket_key, _quarter_bucket_label),
    "year": (_year_bucket_key, _year_bucket_label),
}


# ── Public API ───────────────────────────────────────────────────


@dataclass(frozen=True)
class SpendingBucket:
    """One row in the spending report."""

    key: str  # sort/identity key, e.g. "2026-W21"
    label: str  # human label, e.g. "18 mag – 24 mag 2026"
    total_eur: float  # sum of purchase costs in this bucket
    purchase_count: int  # how many lots fell into this bucket


@dataclass(frozen=True)
class SpendingReport:
    bucket: str  # one of: week, month, quarter, year
    date_from: date | None
    date_to: date | None
    rows: list[SpendingBucket]
    grand_total_eur: float
    grand_purchase_count: int
    # Lots that had purchased_at set but no cost — flagged so the
    # operator can fix the data if the total looks too low.
    missing_cost_count: int


def compute_spending(
    *,
    bucket: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> SpendingReport:
    """Aggregate purchase costs into the requested bucket size.

    Args:
        bucket: one of "week", "month", "quarter", "year".
        date_from, date_to: inclusive date range filter on
            ``InventoryItem.purchased_at``. Both optional.

    Skipped silently: lots with no ``purchased_at`` (can't bucket
    them in time). Counted but not summed: lots with
    ``purchased_at`` set but no ``total_cost_eur`` — surfaced as
    ``missing_cost_count`` so the operator knows the report is
    incomplete.

    Returns a ``SpendingReport`` with rows sorted by bucket key
    descending (newest first).
    """
    if bucket not in _BUCKETERS:
        raise ValueError(f"Unknown bucket: {bucket!r}")
    key_fn, label_fn = _BUCKETERS[bucket]

    q = db.session.query(InventoryItem).filter(
        InventoryItem.purchased_at.is_not(None),
    )
    if date_from is not None:
        q = q.filter(InventoryItem.purchased_at >= date_from)
    if date_to is not None:
        q = q.filter(InventoryItem.purchased_at <= date_to)

    # Aggregate in Python — keeps the bucketer logic DB-agnostic
    # and trivial to test. With our expected volumes (hundreds of
    # lots, not millions) this is fine.
    grouped: dict[str, dict] = {}
    grand_total = 0.0
    grand_count = 0
    missing_cost = 0
    for lot in q:
        d = lot.purchased_at  # not None — filtered
        key = key_fn(d)
        if key not in grouped:
            grouped[key] = {
                "label": label_fn(d),
                "total": 0.0,
                "count": 0,
            }
        if lot.total_cost_eur is not None:
            grouped[key]["total"] += lot.total_cost_eur
            grand_total += lot.total_cost_eur
        else:
            missing_cost += 1
        grouped[key]["count"] += 1
        grand_count += 1

    rows = [
        SpendingBucket(
            key=k,
            label=v["label"],
            total_eur=v["total"],
            purchase_count=v["count"],
        )
        for k, v in grouped.items()
    ]
    # Newest first.
    rows.sort(key=lambda r: r.key, reverse=True)

    return SpendingReport(
        bucket=bucket,
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        grand_total_eur=grand_total,
        grand_purchase_count=grand_count,
        missing_cost_count=missing_cost,
    )
