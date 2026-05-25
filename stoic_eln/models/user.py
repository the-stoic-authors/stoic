"""Stoic ELN — User model with Argon2 password hashing."""

from __future__ import annotations

from datetime import datetime, UTC

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from stoic_eln.extensions import db

_hasher = PasswordHasher()


def _now_utc() -> datetime:
    """Return current UTC time. Naive datetime stored as UTC by convention."""
    return datetime.now(UTC).replace(tzinfo=None)


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
    # Role hierarchy: 'user' < 'supervisor' < 'admin'
    # 'supervisor' can create/edit/delete reactions and substances, but
    # cannot manage users, lab settings, or audit log.
    # 'admin' has full power (and is_admin=True is also set for backward compat).
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    theme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # The user's "current" group: the one whose lots they're consuming and
    # to which their new purchases default. NULL means "use the lab default
    # group". A user can be a member of multiple groups via GroupMembership;
    # this just picks one as the active context.
    default_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("group.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
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

    # ── Role helpers ──────────────────────────────────────────────────
    @property
    def is_supervisor(self) -> bool:
        """True for supervisors AND admins (admins implicitly include sup powers)."""
        return self.role in ("supervisor", "admin") or self.is_admin

    @property
    def can_edit_reactions(self) -> bool:
        """Can create/edit/delete reaction templates and substances."""
        return self.is_supervisor

    @property
    def can_manage_admin(self) -> bool:
        """Can manage users, lab settings, audit log."""
        return self.role == "admin" or self.is_admin

    def sync_role_flags(self) -> None:
        """Keep ``is_admin`` in sync with ``role`` for back-compat."""
        if self.role == "admin":
            self.is_admin = True
        elif self.is_admin and self.role == "user":
            # Pre-existing admin without explicit role → upgrade role.
            self.role = "admin"
