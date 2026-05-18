"""Diagnostic v4 — BYTE-FOR-BYTE COPY of the failing test.

Goal: prove the failing test in test_backup_encryption.py is
identical to one that passes here, so the difference must be the
file's other content (imports, module-level fixtures, or test
ordering).

Run: .venv/bin/pytest tests/diagnose_v4.py -s --no-header -v
"""
from __future__ import annotations

# These imports are EXACTLY the same as test_backup_encryption.py.
# Copy them verbatim so we don't accidentally have a different
# import order or set.
import gzip
import io
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db
from stoic_eln.models.settings import AppSetting
from stoic_eln.services import backup as backup_service
from stoic_eln.services import backup_crypto


# Same file-scoped fixtures as test_backup_encryption.py
# (verbatim copy of encrypted_app, plain_app).

@pytest.fixture
def encrypted_app(tmp_path):
    db_path = tmp_path / "stoic_test.db"
    instance_path = tmp_path / "inst"
    instance_path.mkdir()
    (instance_path / "backup.key").write_text(
        "correct horse battery staple", encoding="utf-8"
    )

    class _EncTestingConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    app = create_app(_EncTestingConfig, instance_path=str(instance_path))
    with app.app_context():
        db.create_all()
        AppSetting.set("backup.path", str(tmp_path / "backups"))
        from stoic_eln.services import passphrase_store as _ps
        _ps.set_source(_ps.SOURCE_FILE)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def plain_app(tmp_path):
    db_path = tmp_path / "stoic_test.db"
    instance_path = tmp_path / "inst"
    instance_path.mkdir()

    class _PlainTestingConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    app = create_app(_PlainTestingConfig, instance_path=str(instance_path))
    with app.app_context():
        db.create_all()
        AppSetting.set("backup.path", str(tmp_path / "backups"))
        yield app
        db.session.remove()
        db.drop_all()


# THE EXACT failing test, copied verbatim.
def test_resolve_passphrase_env_takes_precedence(tmp_path, monkeypatch, app):
    """When source=='env', the env var is returned (the file is
    ignored even if present). Legacy 14.1 test; in the new
    source-driven model (patch 14.3) precedence is determined by
    the configured source rather than a hard-coded order."""
    from stoic_eln.services import passphrase_store as ps
    ps.set_source(ps.SOURCE_ENV)
    (tmp_path / "backup.key").write_text("from-file", encoding="utf-8")
    monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", "from-env")
    assert backup_crypto.resolve_passphrase(tmp_path) == "from-env"
