"""Shared pytest fixtures.

Notes on isolation:

- The default ``app`` fixture creates a fresh Flask app per test.
  We override its ``instance_path`` to point at a per-test temp
  directory so that the passphrase-store machinery (patch 14.3),
  which writes ``auth_source`` markers to ``<instance>/``, does
  not pollute the developer's real ``instance/`` between runs.

- The passphrase store keeps a module-level cache for the
  lifetime of the process. Pytest runs many tests in a single
  process, so we wipe the cache before each test to prevent
  cross-test contamination.

- Some defensive cleanup at session start removes any leftover
  markers in the real instance/ that earlier (pre-patch-14.3)
  test runs may have written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db
from stoic_eln.models.user import User


# ── Session-level cleanup ────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _scrub_real_instance_dir():
    """Remove stale auth_source / backup.key from the real
    ``instance/`` directory at session start. These can be left
    behind by earlier test runs that ran before this fixture
    existed, and would otherwise change the default behaviour of
    fresh apps created by tests."""
    real_instance = Path(__file__).resolve().parents[1] / "instance"
    for stale_name in ("auth_source", "backup.key"):
        stale = real_instance / stale_name
        if stale.exists():
            try:
                stale.unlink()
            except OSError:
                pass
    yield


# ── Per-test isolation ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_passphrase_cache():
    """Wipe the in-process passphrase cache + injected prompt
    callback before AND after each test.

    The cache and callback live at module scope in
    ``passphrase_store``; without this fixture a test that sets a
    callback would silently leak into the next test in the same
    pytest session."""
    from stoic_eln.services import passphrase_store as _ps
    _ps.reset_cache()
    _ps.set_prompt_callback(None)
    yield
    _ps.reset_cache()
    _ps.set_prompt_callback(None)


@pytest.fixture(autouse=True)
def _no_env_passphrase(monkeypatch):
    """Ensure tests don't inherit a real STOIC_BACKUP_PASSPHRASE
    from the developer's shell. Tests that need it set it
    themselves via monkeypatch."""
    monkeypatch.delenv("STOIC_BACKUP_PASSPHRASE", raising=False)


# ── App fixtures ─────────────────────────────────────────────────


@pytest.fixture
def app(tmp_path_factory):
    """Create a fresh app per test, with instance_path redirected
    to a per-test temp directory.

    The redirection is essential for tests touching the
    passphrase-store source marker (``<instance>/auth_source``)
    or the backup keyfile (``<instance>/backup.key``). Without
    it, two tests in the same session would see each other's
    marker writes through the shared real ``instance/`` dir.

    We use ``tmp_path_factory`` rather than the per-test
    ``tmp_path`` so the isolated instance lives in a *separate*
    subtree from the test's own scratch dir. Some tests do
    things like ``len(list(tmp_path.iterdir()))`` to count files
    they created; if we used tmp_path/instance/ here, those tests
    would see an unexpected extra entry.

    The instance_path is passed straight to ``create_app``, which
    forwards it to Flask. This means it's set BEFORE any boot
    hook (``_register_extensions``, ``_maybe_enable_sqlcipher``)
    runs — so the hooks read the isolated location from the start
    rather than the developer's real ``instance/``."""
    isolated_instance = tmp_path_factory.mktemp("stoic-instance")

    app = create_app(TestingConfig, instance_path=str(isolated_instance))

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
