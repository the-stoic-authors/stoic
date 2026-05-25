"""Stoic ELN — Audit log query service (Settimana 6 patch 8).

Read-side helpers for the AuditLog table. The write side
(``log_event``) is in ``stoic_eln.services.audit``.

Two surfaces:
  - ``query_events(...)``  — paginated table with filters
  - ``recent_events(n)``   — most recent N events for the dashboard

Both honour the same filtering vocabulary so the dashboard widget
can deep-link to the full audit page with its filters preserved.

Action labels (Italian) and Bootstrap colours are centralised here
so the dashboard timeline and the table page stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_

from stoic_eln.extensions import db
from stoic_eln.models.audit import AuditLog
from stoic_eln.models.user import User


# ── Action labels ──────────────────────────────────────────────────


# Map of canonical action verbs to (italian label, bootstrap color)
# Falls back to (action, "secondary") for unknown verbs.
_ACTION_LABELS: dict[str, tuple[str, str]] = {
    # Auth
    "login": ("accesso", "secondary"),
    "logout": ("uscita", "secondary"),
    "login_failed": ("accesso fallito", "danger"),
    # Reactions
    "create_draft": ("bozza creata", "secondary"),
    "publish": ("pubblicato", "success"),
    "edit_started": ("inizio modifica", "secondary"),
    "edit_cancelled": ("modifica annullata", "secondary"),
    "archive": ("archiviato", "warning"),
    "deactivate": ("disattivato", "warning"),
    "reactivate": ("riattivato", "success"),
    # Substances
    "create": ("creato", "primary"),
    "update": ("aggiornato", "primary"),
    "delete": ("eliminato", "danger"),
    "read": ("consultato", "light"),
    # Inventory
    "create_lot": ("lotto creato", "primary"),
    "update_lot": ("lotto aggiornato", "primary"),
    "deactivate_lot": ("lotto disattivato", "warning"),
    # Orders
    "create_order": ("ordine pianificato", "primary"),
    "update_order": ("ordine aggiornato", "primary"),
    "mark_order_ordered": ("ordine confermato", "info"),
    "receive_order": ("ordine ricevuto", "success"),
    "cancel_order": ("ordine annullato", "warning"),
    "bulk_create_orders_from_shopping_list": ("ordini bulk", "primary"),
    "update_shopping_list_settings": ("settaggi spesa", "secondary"),
    # Runs
    "run_create_draft": ("run creato", "primary"),
    "run_start": ("run avviato", "info"),
    "run_complete": ("run completato", "success"),
    "run_cancel": ("run annullato", "warning"),
    "run_set_lot": ("lotto su run", "secondary"),
    "run_set_actual": ("quantità run", "secondary"),
    # Settings
    "update_settings": ("impostazioni aggiornate", "secondary"),
}


def label_for_action(action: str) -> tuple[str, str]:
    """(label_it, bootstrap_color) — falls back to action itself."""
    return _ACTION_LABELS.get(action, (action.replace("_", " "), "secondary"))


# ── Filters / dataclasses ──────────────────────────────────────────


@dataclass
class AuditFilters:
    """Normalized audit query filters."""
    user_id: int | None = None
    action: str | None = None
    entity_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    q: str | None = None       # free-text in details/entity_id

    def is_empty(self) -> bool:
        return all(v is None for v in (
            self.user_id, self.action, self.entity_type,
            self.date_from, self.date_to, self.q,
        ))


@dataclass
class AuditPage:
    """One page of audit events plus paging metadata."""
    events: list[AuditLog]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


# ── Query helpers ──────────────────────────────────────────────────


def _apply_filters(query, f: AuditFilters):
    if f.user_id is not None:
        query = query.filter(AuditLog.user_id == f.user_id)
    if f.action:
        query = query.filter(AuditLog.action == f.action)
    if f.entity_type:
        query = query.filter(AuditLog.entity_type == f.entity_type)
    if f.date_from:
        # midnight UTC of date_from
        dt_from = datetime.combine(f.date_from, time.min)
        query = query.filter(AuditLog.created_at >= dt_from)
    if f.date_to:
        # end of day UTC of date_to (inclusive)
        dt_to = datetime.combine(f.date_to + timedelta(days=1), time.min)
        query = query.filter(AuditLog.created_at < dt_to)
    if f.q:
        like = f"%{f.q}%"
        # Match action, entity_type, entity_id, details JSON dump
        # SQLite stores JSON as TEXT, so a LIKE works for free-text search
        query = query.filter(or_(
            AuditLog.action.ilike(like),
            AuditLog.entity_type.ilike(like),
            db.cast(AuditLog.entity_id, db.String).ilike(like),
            db.cast(AuditLog.details, db.String).ilike(like),
        ))
    return query


def query_events(filters: AuditFilters,
                 *, page: int = 1, page_size: int = 50) -> AuditPage:
    """Paginated, filtered query — newest first."""
    page = max(1, page)
    page_size = max(1, min(page_size, 500))

    base = db.session.query(AuditLog)
    base = _apply_filters(base, filters)

    total = base.count()
    events = (base
              .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
              .offset((page - 1) * page_size)
              .limit(page_size).all())
    return AuditPage(events=events, total=total, page=page, page_size=page_size)


def recent_events(n: int = 10,
                  *, filters: AuditFilters | None = None) -> list[AuditLog]:
    """Most recent N events, optionally filtered. For dashboard widget."""
    n = max(1, min(n, 200))
    base = db.session.query(AuditLog)
    if filters is not None:
        base = _apply_filters(base, filters)
    return (base
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(n).all())


# ── Distinct values for filter dropdowns ───────────────────────────


def distinct_actions() -> list[str]:
    rows = (db.session.query(AuditLog.action)
            .filter(AuditLog.action.isnot(None))
            .distinct().order_by(AuditLog.action.asc()).all())
    return [r[0] for r in rows if r[0]]


def distinct_entity_types() -> list[str]:
    rows = (db.session.query(AuditLog.entity_type)
            .filter(AuditLog.entity_type.isnot(None))
            .distinct().order_by(AuditLog.entity_type.asc()).all())
    return [r[0] for r in rows if r[0]]


def distinct_users() -> list[User]:
    """Users who have generated at least one audit event."""
    rows = (db.session.query(User)
            .join(AuditLog, AuditLog.user_id == User.id)
            .distinct().order_by(User.full_name.asc()).all())
    return rows


# ── CSV export ─────────────────────────────────────────────────────


def export_csv(filters: AuditFilters) -> str:
    """Return a CSV string of all matching events (no paging)."""
    import csv
    import io
    import json

    base = _apply_filters(db.session.query(AuditLog), filters)
    events = (base
              .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
              .all())

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "id", "created_at_utc", "user_id", "user_name", "action",
        "entity_type", "entity_id", "ip_address", "details_json",
    ])
    for e in events:
        u = e.user_id and db.session.get(User, e.user_id)
        w.writerow([
            e.id,
            e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
            e.user_id or "",
            (u.full_name if u else ""),
            e.action or "",
            e.entity_type or "",
            e.entity_id if e.entity_id is not None else "",
            e.ip_address or "",
            json.dumps(e.details, ensure_ascii=False) if e.details else "",
        ])
    return buf.getvalue()


# ── Free-text formatting for one event ─────────────────────────────


def describe_event(event: AuditLog) -> str:
    """A short human-readable line for one event."""
    label, _color = label_for_action(event.action or "")
    parts = [label]
    if event.entity_type:
        parts.append(event.entity_type)
    if event.entity_id is not None:
        parts.append(f"#{event.entity_id}")
    return " · ".join(parts)
