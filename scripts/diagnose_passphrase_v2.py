"""Diagnostic v2 — reproduces the EXACT fixture chain of conftest.py
to find where the divergence sits.

Run: .venv/bin/pytest scripts/diagnose_passphrase_v2.py -s --no-header -v
"""
from __future__ import annotations

import os
import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db


# ── Same autouse fixtures as conftest.py ────────────────────────────


@pytest.fixture(autouse=True)
def _reset_passphrase_cache():
    from stoic_eln.services import passphrase_store as _ps
    _ps.reset_cache()
    _ps.set_prompt_callback(None)
    print("  [autouse] _reset_passphrase_cache pre-yield")
    yield
    _ps.reset_cache()
    _ps.set_prompt_callback(None)
    print("  [autouse] _reset_passphrase_cache post-yield")


@pytest.fixture(autouse=True)
def _no_env_passphrase(monkeypatch):
    print(f"  [autouse] _no_env_passphrase pre-yield: "
          f"env={os.environ.get('STOIC_BACKUP_PASSPHRASE')!r}")
    monkeypatch.delenv("STOIC_BACKUP_PASSPHRASE", raising=False)
    print(f"  [autouse] after delenv: "
          f"env={os.environ.get('STOIC_BACKUP_PASSPHRASE')!r}")


@pytest.fixture
def app(tmp_path_factory):
    isolated_instance = tmp_path_factory.mktemp("stoic-instance")
    print(f"  [app fixture] instance_path = {isolated_instance}")
    app = create_app(TestingConfig, instance_path=str(isolated_instance))
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


# ── Reproduce the exact failing test ─────────────────────────────────


def test_resolve_passphrase_env_takes_precedence(tmp_path, monkeypatch, app):
    """COPY of the actual failing test from test_backup_encryption.py
    line 160, but with verbose prints around each step.
    """
    print()
    print("=" * 60)
    print("TEST BODY")
    print("=" * 60)

    print(f"  test_body: STOIC_BACKUP_PASSPHRASE env = "
          f"{os.environ.get('STOIC_BACKUP_PASSPHRASE')!r}")

    from stoic_eln.services import passphrase_store as ps
    from stoic_eln.services import backup_crypto

    # Set source to ENV (this is what the test does first)
    ps.set_source(ps.SOURCE_ENV)
    print(f"  after set_source(ENV): current_source() = {ps.current_source()!r}")

    # Write the file (should be ignored because source=ENV)
    (tmp_path / "backup.key").write_text("from-file", encoding="utf-8")
    print(f"  wrote backup.key at {tmp_path / 'backup.key'}")

    # Set env var
    monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", "from-env")
    print(f"  after setenv: STOIC_BACKUP_PASSPHRASE = "
          f"{os.environ.get('STOIC_BACKUP_PASSPHRASE')!r}")

    # Diagnostic: what does each function see?
    print()
    print(f"  ps.current_source() = {ps.current_source()!r}")
    print(f"  ps._from_env() = {ps._from_env()!r}")
    print(f"  ps.get_passphrase(tmp_path) = {ps.get_passphrase(tmp_path)!r}")
    print()

    # The actual assertion that fails on Rico's Mac
    result = backup_crypto.resolve_passphrase(tmp_path)
    print(f"  backup_crypto.resolve_passphrase(tmp_path) = {result!r}")

    print("=" * 60)
    assert result == "from-env", (
        f"Expected 'from-env', got {result!r}"
    )
