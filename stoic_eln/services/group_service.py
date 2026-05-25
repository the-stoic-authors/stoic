"""Stoic ELN — Group service (Settimana 6).

Helper functions for group management:
  - ``ensure_default_group()`` — creates the lab-wide default group if
    missing. Idempotent. Used in test fixtures and on first boot.
  - ``current_user_group(user)`` — returns the user's current default
    group, falling back to the lab-wide default group.
  - ``ensure_membership(user, group)`` — adds a membership if missing.
"""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models.group import Group, GroupMembership


def ensure_default_group() -> Group:
    """Return the Default group, creating it if needed."""
    g = db.session.query(Group).filter(Group.slug == "default").one_or_none()
    if g is None:
        g = Group(
            slug="default",
            name="Default",
            description="Gruppo di default del laboratorio.",
            is_default=True,
            is_active=True,
        )
        db.session.add(g)
        db.session.flush()
    return g


def ensure_membership(user, group: Group, *, role: str = "member") -> GroupMembership:
    """Add the user to the group if not already a member."""
    existing = (
        db.session.query(GroupMembership)
        .filter(GroupMembership.user_id == user.id, GroupMembership.group_id == group.id)
        .one_or_none()
    )
    if existing:
        return existing
    m = GroupMembership(user_id=user.id, group_id=group.id, role=role)
    db.session.add(m)
    db.session.flush()
    return m


def current_user_group(user) -> Group:
    """Return the user's current group, or the lab default group."""
    if user.default_group_id:
        g = db.session.get(Group, user.default_group_id)
        if g and g.is_active:
            return g
    return ensure_default_group()
