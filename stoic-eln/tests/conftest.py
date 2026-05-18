"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db
from stoic_eln.models.user import User


@pytest.fixture
def app():
    """Create a fresh app per test."""
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """A test HTTP client for the app."""
    return app.test_client()


@pytest.fixture
def admin_user(app):
    """Create a test admin user."""
    user = User(
        username="testadmin",
        full_name="Test Admin",
        operator_code="TST",
        is_admin=True,
        is_active=True,
        locale="it",
    )
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user
