"""Quick diagnostic — reproduces what test_resolve_passphrase_env_takes_precedence
does, step by step, with prints so we can see where it goes wrong on Rico's Mac.

Run with: .venv/bin/pytest scripts/diagnose_passphrase.py -s --no-header -v
"""
from __future__ import annotations

import os
import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db


def test_diagnose_resolve_env(tmp_path, monkeypatch):
    print()
    print("=" * 60)
    print("DIAGNOSTIC: resolve_passphrase with source=env")
    print("=" * 60)

    isolated = tmp_path / "instance"
    isolated.mkdir()
    app = create_app(TestingConfig, instance_path=str(isolated))
    print(f"app.instance_path = {app.instance_path}")

    with app.app_context():
        db.create_all()

        from stoic_eln.services import passphrase_store as ps
        from stoic_eln.models.settings import AppSetting
        from stoic_eln.services import backup_crypto

        # Reset state
        ps.reset_cache()
        print(f"is_cached (before): {ps.is_cached()}")

        # Set source to ENV
        ps.set_source(ps.SOURCE_ENV)
        print(f"set_source(ENV) called")

        # Read it back from AppSetting
        from_db = AppSetting.get("auth.passphrase_source")
        print(f"AppSetting.get('auth.passphrase_source') = {from_db!r}")

        # Read it back from current_source()
        cs = ps.current_source()
        print(f"current_source() = {cs!r}")

        # Read it back from marker
        marker = isolated / "auth_source"
        print(f"marker exists: {marker.exists()}")
        if marker.exists():
            print(f"marker content: {marker.read_text().strip()!r}")

        # Set env var
        monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", "from-env")
        print(f"env STOIC_BACKUP_PASSPHRASE = {os.environ.get('STOIC_BACKUP_PASSPHRASE')!r}")

        # Now call resolve_passphrase
        result = backup_crypto.resolve_passphrase(tmp_path)
        print(f"resolve_passphrase result = {result!r}")

        # Direct call to from_env
        direct = ps._from_env()
        print(f"ps._from_env() direct = {direct!r}")

        # Direct call to get_passphrase
        gp = ps.get_passphrase(tmp_path)
        print(f"ps.get_passphrase() direct = {gp!r}")

        print("=" * 60)
        assert result == "from-env", (
            f"Expected 'from-env', got {result!r}. "
            f"current_source={cs!r}, from_env_direct={direct!r}"
        )
