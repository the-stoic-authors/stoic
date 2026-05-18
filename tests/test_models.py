"""Tests for SQLAlchemy models."""

from __future__ import annotations

from stoic_eln.extensions import db
from stoic_eln.models.user import User
from stoic_eln.models.audit import AuditLog
from stoic_eln.models.settings import AppSetting


def test_user_password_hashing(app):
    user = User(username="alice", full_name="Alice", is_active=True)
    user.set_password("secret123")
    assert user.password_hash != "secret123"
    assert user.check_password("secret123") is True
    assert user.check_password("wrong") is False


def test_user_unique_username(app):
    u1 = User(username="bob", full_name="Bob", is_active=True)
    u1.set_password("x" * 12)
    db.session.add(u1)
    db.session.commit()

    import sqlalchemy.exc

    u2 = User(username="bob", full_name="Bob 2", is_active=True)
    u2.set_password("y" * 12)
    db.session.add(u2)
    try:
        db.session.commit()
        raise AssertionError("Expected IntegrityError")
    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()


def test_audit_log_create(app):
    event = AuditLog(action="login", entity_type="user", entity_id=1)
    db.session.add(event)
    db.session.commit()
    assert event.id is not None
    assert event.created_at is not None


def test_app_setting_get_set(app):
    AppSetting.set("lab_name", "Acme Labs")
    assert AppSetting.get("lab_name") == "Acme Labs"
    AppSetting.set("lab_name", "New Name")
    assert AppSetting.get("lab_name") == "New Name"
    assert AppSetting.get("nonexistent", default="x") == "x"
