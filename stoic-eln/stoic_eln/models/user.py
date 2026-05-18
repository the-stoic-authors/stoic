"""Stoic ELN — User model with Argon2 password hashing."""

from __future__ import annotations

from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from stoic_eln.extensions import db

_hasher = PasswordHasher()


def _now_utc() -> datetime:
    """Return current UTC time. Naive datetime stored as UTC by convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model, UserMixin):
    """An application user."""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    operator_code: Mapped[str | None] = mapped_column(
        String(10), unique=True, nullable=True, index=True
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    theme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def set_password(self, password: str) -> None:
        """Hash and store the password using Argon2."""
        self.password_hash = _hasher.hash(password)

    def check_password(self, password: str) -> bool:
        """Verify a candidate password against the stored hash."""
        if not self.password_hash:
            return False
        try:
            return _hasher.verify(self.password_hash, password)
        except VerifyMismatchError:
            return False

    def needs_rehash(self) -> bool:
        """Return True if the stored hash uses outdated Argon2 parameters."""
        return _hasher.check_needs_rehash(self.password_hash)

    def __repr__(self) -> str:
        return f"<User {self.username!r}>"
