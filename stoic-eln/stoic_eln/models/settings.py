"""Stoic ELN — Runtime-configurable application settings (key-value store)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from stoic_eln.extensions import db


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AppSetting(db.Model):
    """A single key-value setting. Editable by admins via the UI."""

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, onupdate=_now_utc, nullable=False
    )

    def __repr__(self) -> str:
        return f"<AppSetting {self.key}={self.value!r}>"

    @classmethod
    def get(cls, key: str, default: str | None = None) -> str | None:
        """Return the value for ``key``, or ``default`` if not set."""
        item = db.session.get(cls, key)
        return item.value if item else default

    @classmethod
    def set(cls, key: str, value: str | None) -> None:
        """Insert or update a setting and commit."""
        item = db.session.get(cls, key)
        if item is None:
            item = cls(key=key, value=value)
            db.session.add(item)
        else:
            item.value = value
        db.session.commit()
