"""Stoic ELN — Group and GroupMembership models (Settimana 6).

Groups are research teams or projects that own inventory lots, runs,
and reactions. The model is deliberately lightweight: a Group is just
a named container with a ``slug`` (the URL-safe identifier) and an
``is_default`` flag for the lab-wide group created by the migration.

Membership is many-to-many via ``group_membership`` with an optional
``role`` per group (e.g. 'leader', 'member'). At runtime the user's
*current* group (the one whose lots they're consuming and to which
their new purchases are attributed) is stored in ``user.default_group_id``.

For now Stoic creates one Group called 'Default' that contains all
existing users, and all existing inventory lots are assigned to it.
This is the lab-wide configuration. Multi-group setups are possible
in the future when the user wants to separate finances by sub-team
or project.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db

if TYPE_CHECKING:
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Group(db.Model):
    """A research group / project that owns inventory and runs."""

    __tablename__ = "group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, nullable=False
    )

    memberships: Mapped[list[GroupMembership]] = relationship(
        "GroupMembership",
        back_populates="group",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Group #{self.id} {self.slug}>"


class GroupMembership(db.Model):
    """Link table: a User belongs to a Group with an optional role."""

    __tablename__ = "group_membership"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_user_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("group.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(
        String(16), default="member", nullable=False,
    )
    """One of: 'leader', 'member'."""
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, nullable=False,
    )

    group: Mapped[Group] = relationship("Group", back_populates="memberships")
    user: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<GroupMembership user={self.user_id} group={self.group_id}>"
        )
