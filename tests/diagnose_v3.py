"""Diagnostic v3 — placed inside tests/ so it uses the REAL conftest.

Same test as test_backup_encryption.py::test_resolve_passphrase_env_takes_precedence,
but with print statements that reveal what state the conftest fixtures
leave behind.

Run: .venv/bin/pytest tests/diagnose_v3.py -s --no-header -v
"""
from __future__ import annotations

import os

from stoic_eln.services import backup_crypto


def test_v3_reproduce_with_prints(tmp_path, monkeypatch, app):
    """COPY of the failing test, with diagnostic prints AROUND it."""
    print()
    print("=" * 60)
    print("DIAGNOSTIC v3 — running INSIDE tests/ (real conftest)")
    print("=" * 60)

    print(f"  app object id: {id(app)}")
    print(f"  app.instance_path: {app.instance_path}")
    print(f"  app.config['TESTING']: {app.config.get('TESTING')}")
    print(f"  app.config['SQLALCHEMY_DATABASE_URI']: "
          f"{app.config.get('SQLALCHEMY_DATABASE_URI')}")

    from stoic_eln.services import passphrase_store as ps

    # Pre-test state
    print()
    print("  Pre-test state:")
    print(f"    is_cached: {ps.is_cached()}")
    print(f"    current_source(): {ps.current_source()!r}")
    print(f"    env STOIC_BACKUP_PASSPHRASE: "
          f"{os.environ.get('STOIC_BACKUP_PASSPHRASE')!r}")

    # Check marker file
    from pathlib import Path
    marker = Path(app.instance_path) / "auth_source"
    print(f"    marker exists at {marker}: {marker.exists()}")
    if marker.exists():
        print(f"    marker content: {marker.read_text().strip()!r}")

    # Now do EXACTLY what the failing test does
    print()
    print("  --- now doing what the failing test does ---")
    ps.set_source(ps.SOURCE_ENV)
    print("    after set_source(ENV):")
    print(f"      current_source() = {ps.current_source()!r}")
    print(f"      marker now exists: {marker.exists()}")
    if marker.exists():
        print(f"      marker content: {marker.read_text().strip()!r}")

    # AppSetting check
    from stoic_eln.models.settings import AppSetting
    db_value = AppSetting.get("auth.passphrase_source")
    print(f"      AppSetting.get('auth.passphrase_source'): {db_value!r}")

    # Write the dummy file (test does this)
    (tmp_path / "backup.key").write_text("from-file", encoding="utf-8")

    # Set env
    monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", "from-env")
    print(f"    after setenv: env = "
          f"{os.environ.get('STOIC_BACKUP_PASSPHRASE')!r}")

    # Diagnostics before the call
    print()
    print("  Right before resolve_passphrase call:")
    print(f"    ps._from_env() = {ps._from_env()!r}")
    print(f"    ps.is_cached() = {ps.is_cached()}")
    print(f"    ps.current_source() = {ps.current_source()!r}")

    # The actual call
    result = backup_crypto.resolve_passphrase(tmp_path)
    print()
    print(f"  RESULT: backup_crypto.resolve_passphrase(tmp_path) = {result!r}")

    print("=" * 60)
    assert result == "from-env", f"Expected 'from-env', got {result!r}"
