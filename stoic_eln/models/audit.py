"""Stoic ELN — Audit log model. Append-only, immutable."""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from stoic_eln.extensions import db


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AuditLog(db.Model):
    """A single event in the audit log.

    Events are append-only. They should never be modified or deleted from
    application code; they may be archived periodically by a maintenance job.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<AuditLog #{self.id} {self.action} {self.entity_type}>"
