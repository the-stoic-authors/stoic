"""Tests for patch 14.1 — encrypted backup flow.

When a passphrase is configured (via env var or instance/backup.key),
``create_backup`` produces an encrypted file (.db.gz.enc) and
``restore_backup`` decrypts it transparently. Unencrypted backups
keep working (backward compatible).
"""

from __future__ import annotations

import gzip
import os
import sqlite3
from pathlib import Path

import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db
from stoic_eln.models.settings import AppSetting
from stoic_eln.services import backup as backup_service
from stoic_eln.services import backup_crypto


# ── Fixture: file-backed app with a passphrase file ──────────────


@pytest.fixture
def encrypted_app(tmp_path):
    """An app whose instance/ dir contains a backup.key file
    AND has the passphrase source configured to 'file'.

    The DB lives on disk under tmp_path. The fixture sets
    ``AppSetting.auth.passphrase_source = 'file'`` (patch 14.3
    model) so the backup service treats this as an
    encryption-enabled deployment.
    """
    db_path = tmp_path / "stoic_test.db"
    instance_path = tmp_path / "inst"
    instance_path.mkdir()

    # Drop a passphrase file
    (instance_path / "backup.key").write_text("correct horse battery staple", encoding="utf-8")

    class _EncTestingConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    # Passing instance_path upfront ensures the boot hook
    # (_maybe_enable_sqlcipher) sees the test's isolated path
    # rather than the developer's real instance/.
    app = create_app(_EncTestingConfig, instance_path=str(instance_path))

    with app.app_context():
        db.create_all()
        AppSetting.set("backup.path", str(tmp_path / "backups"))
        # Switch passphrase source to FILE so resolve_passphrase
        # reads instance/backup.key. Otherwise the default
        # (SOURCE_NONE) would skip the file even if it exists.
        from stoic_eln.services import passphrase_store as _ps

        _ps.set_source(_ps.SOURCE_FILE)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def plain_app(tmp_path):
    """An app with NO passphrase configured. Should produce
    plain .db.gz backups (legacy 14.0 behaviour).

    Source is SOURCE_NONE (the patch 14.3 default), which means
    create_backup never tries to encrypt."""
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


# ── Crypto module tests (no Flask context) ───────────────────────


def test_encrypt_decrypt_roundtrip():
    """Encrypting and decrypting under the same passphrase yields
    the original plaintext."""
    plaintext = b"Hello, Stoic." * 50
    ct = backup_crypto.encrypt_bytes(plaintext, "pass1234")
    assert ct != plaintext
    assert backup_crypto.is_encrypted(ct[:8])
    pt = backup_crypto.decrypt_bytes(ct, "pass1234")
    assert pt == plaintext


def test_wrong_passphrase_fails_authenticated():
    """A wrong passphrase raises (AES-GCM authentication fails)."""
    from cryptography.exceptions import InvalidTag

    ct = backup_crypto.encrypt_bytes(b"secret", "right")
    with pytest.raises(InvalidTag):
        backup_crypto.decrypt_bytes(ct, "wrong")


def test_tampered_blob_fails():
    """Flipping a byte in the ciphertext fails the GCM auth check."""
    from cryptography.exceptions import InvalidTag

    ct = bytearray(backup_crypto.encrypt_bytes(b"secret", "pw"))
    # Flip a bit deep in the ciphertext (past the header)
    ct[50] ^= 0x01
    with pytest.raises(InvalidTag):
        backup_crypto.decrypt_bytes(bytes(ct), "pw")


def test_each_encryption_is_unique():
    """Probabilistic encryption: same plaintext + key → different ciphertexts."""
    ct1 = backup_crypto.encrypt_bytes(b"same", "pw")
    ct2 = backup_crypto.encrypt_bytes(b"same", "pw")
    assert ct1 != ct2  # different salt + nonce
    # Both should decrypt to the same thing though.
    assert (
        backup_crypto.decrypt_bytes(ct1, "pw") == backup_crypto.decrypt_bytes(ct2, "pw") == b"same"
    )


def test_magic_detection():
    """is_encrypted distinguishes our format from gzip and noise."""
    enc = backup_crypto.encrypt_bytes(b"x", "pw")
    assert backup_crypto.is_encrypted(enc[:8])
    # gzip magic
    assert not backup_crypto.is_encrypted(b"\x1f\x8b\x08\x00\x00\x00\x00\x00")
    # zeros
    assert not backup_crypto.is_encrypted(b"\x00" * 8)
    # too short
    assert not backup_crypto.is_encrypted(b"STOIC")


def test_verify_passphrase_ok():
    """The self-test passes with a reasonable passphrase."""
    r = backup_crypto.verify_passphrase("any-string-works")
    assert r.ok
    assert r.error is None


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


def test_resolve_passphrase_file_used_when_env_absent(tmp_path, monkeypatch, app):
    """When source=='file', the file is read regardless of env var."""
    from stoic_eln.services import passphrase_store as ps

    ps.set_source(ps.SOURCE_FILE)
    monkeypatch.delenv("STOIC_BACKUP_PASSPHRASE", raising=False)
    (tmp_path / "backup.key").write_text("from-file", encoding="utf-8")
    assert backup_crypto.resolve_passphrase(tmp_path) == "from-file"


def test_resolve_passphrase_returns_none_when_source_is_none(tmp_path, app):
    """When source=='none' (the default), no passphrase is
    returned even if a file or env var is set."""
    from stoic_eln.services import passphrase_store as ps

    ps.set_source(ps.SOURCE_NONE)
    (tmp_path / "backup.key").write_text("would-be-returned", encoding="utf-8")
    assert backup_crypto.resolve_passphrase(tmp_path) is None


def test_write_passphrase_file_atomic(tmp_path):
    """write_passphrase_file produces a single file with the
    passphrase, no leftover tmp file."""
    backup_crypto.write_passphrase_file(tmp_path, "my-pass")
    assert (tmp_path / "backup.key").read_text() == "my-pass"
    # No tmp file left behind
    tmps = list(tmp_path.glob("*.tmp"))
    assert tmps == []


def test_write_passphrase_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        backup_crypto.write_passphrase_file(tmp_path, "")
    with pytest.raises(ValueError):
        backup_crypto.write_passphrase_file(tmp_path, "   ")


# ── Integration: encrypted backup end-to-end ─────────────────────


def test_create_backup_produces_encrypted_file(encrypted_app):
    """When a passphrase is configured, the backup file has the
    .db.gz.enc extension and starts with our magic."""
    with encrypted_app.app_context():
        AppSetting.set("test.marker", "alpha")
        db.session.commit()

        bf = backup_service.create_backup(reason="test")
        assert bf.encrypted is True
        assert bf.path.name.endswith(".db.gz.enc")

        # The file on disk starts with STOICENC.
        blob = bf.path.read_bytes()
        assert backup_crypto.is_encrypted(blob[:8])

        # No .db.gz left behind alongside the encrypted file.
        leftovers = list(bf.path.parent.glob("*.db.gz"))
        assert leftovers == []


def test_encrypted_backup_decrypts_to_valid_sqlite(encrypted_app, tmp_path):
    """The encrypted blob, when decrypted with the right
    passphrase, yields a valid gzipped SQLite that contains our
    seeded data."""
    with encrypted_app.app_context():
        AppSetting.set("test.marker", "alpha")
        db.session.commit()

        bf = backup_service.create_backup(reason="test")
        blob = bf.path.read_bytes()

        # Decrypt manually using the same passphrase.
        plaintext = backup_crypto.decrypt_bytes(blob, "correct horse battery staple")
        # Plaintext should itself be gzipped SQLite.
        assert plaintext[:2] == b"\x1f\x8b"  # gzip magic

        # Ungzip and open as SQLite.
        sql_bytes = gzip.decompress(plaintext)
        decoded = tmp_path / "decoded.db"
        decoded.write_bytes(sql_bytes)
        conn = sqlite3.connect(str(decoded))
        cur = conn.execute("SELECT value FROM app_setting WHERE key=?", ("test.marker",))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "alpha"


def test_restore_encrypted_backup(encrypted_app):
    """End-to-end: create encrypted backup, mutate DB, restore,
    verify the original value is back."""
    with encrypted_app.app_context():
        AppSetting.set("test.marker", "alpha")
        db.session.commit()

        bf = backup_service.create_backup(reason="test")
        live_db = backup_service.get_db_path()

        AppSetting.set("test.marker", "beta")
        db.session.commit()

        backup_service.restore_backup(bf.filename)

        # Verify via fresh sqlite connection (SQLAlchemy session is
        # disposed by restore_backup).
        conn = sqlite3.connect(str(live_db))
        cur = conn.execute("SELECT value FROM app_setting WHERE key=?", ("test.marker",))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "alpha"


def test_restore_encrypted_fails_without_passphrase(encrypted_app):
    """If we delete the passphrase file before restoring, the
    restore must refuse rather than corrupt the live DB. The
    audit log still records the attempt (so the file does change
    in that one row), but the user data must be intact."""
    from stoic_eln.services import passphrase_store as _ps

    with encrypted_app.app_context():
        AppSetting.set("test.marker", "alpha")
        db.session.commit()
        bf = backup_service.create_backup(reason="test")

        live_db = backup_service.get_db_path()

        # Remove the passphrase from disk AND from the in-process
        # cache (patch 14.3 caches after first read).
        (Path(encrypted_app.instance_path) / "backup.key").unlink()
        os.environ.pop("STOIC_BACKUP_PASSPHRASE", None)
        _ps.reset_cache()

        with pytest.raises(RuntimeError, match="encrypted but no passphrase"):
            backup_service.restore_backup(bf.filename)

        # Live DB must still be a valid SQLite file with our data.
        assert live_db.exists()
        conn = sqlite3.connect(str(live_db))
        try:
            row = conn.execute(
                "SELECT value FROM app_setting WHERE key=?", ("test.marker",)
            ).fetchone()
            assert row is not None
            assert row[0] == "alpha"
        finally:
            conn.close()


def test_restore_encrypted_fails_with_wrong_passphrase(encrypted_app):
    """Wrong passphrase: restore fails with a clear error, live
    DB is left valid with the pre-attempt data."""
    from stoic_eln.services import passphrase_store as _ps

    with encrypted_app.app_context():
        AppSetting.set("test.marker", "alpha")
        db.session.commit()
        bf = backup_service.create_backup(reason="test")

        live_db = backup_service.get_db_path()

        # Overwrite the passphrase with a wrong one AND reset
        # the cache so the next read picks up the new value.
        (Path(encrypted_app.instance_path) / "backup.key").write_text(
            "wrong-passphrase", encoding="utf-8"
        )
        _ps.reset_cache()

        with pytest.raises(RuntimeError, match="Cannot decrypt"):
            backup_service.restore_backup(bf.filename)

        # Live DB is a valid SQLite with the original data.
        conn = sqlite3.connect(str(live_db))
        try:
            row = conn.execute(
                "SELECT value FROM app_setting WHERE key=?", ("test.marker",)
            ).fetchone()
            assert row is not None
            assert row[0] == "alpha"
        finally:
            conn.close()


# ── Backward compatibility ───────────────────────────────────────


def test_plain_backup_still_works_without_passphrase(plain_app):
    """No passphrase configured: backups are plain .db.gz (14.0
    behaviour). Restore works as before."""
    with plain_app.app_context():
        AppSetting.set("test.marker", "alpha")
        db.session.commit()

        bf = backup_service.create_backup(reason="test")
        assert bf.encrypted is False
        assert bf.path.name.endswith(".db.gz")
        assert not bf.path.name.endswith(".db.gz.enc")

        # Restore works.
        AppSetting.set("test.marker", "beta")
        db.session.commit()
        backup_service.restore_backup(bf.filename)

        conn = sqlite3.connect(str(backup_service.get_db_path()))
        row = conn.execute("SELECT value FROM app_setting WHERE key=?", ("test.marker",)).fetchone()
        conn.close()
        assert row[0] == "alpha"


def test_list_backups_reports_encryption_flag(encrypted_app):
    """The BackupFile.encrypted flag correctly distinguishes
    encrypted (.db.gz.enc) from plain (.db.gz) entries even when
    both exist side by side."""
    with encrypted_app.app_context():
        backup_dir = backup_service.get_backup_dir()
        # Encrypted (real)
        bf_enc = backup_service.create_backup(reason="test")

        # Plain (simulate a legacy file alongside)
        plain_name = "stoic_eln-20260101-000000.db.gz"
        (backup_dir / plain_name).write_bytes(b"\x1f\x8b\x00\x00fake")

        items = backup_service.list_backups()
        by_name = {b.filename: b for b in items}
        assert by_name[bf_enc.filename].encrypted is True
        assert by_name[plain_name].encrypted is False


def test_parse_timestamp_accepts_both_extensions():
    """Filename parser handles .db.gz and .db.gz.enc."""
    a = backup_service._parse_timestamp("stoic_eln-20260101-120000.db.gz")
    b = backup_service._parse_timestamp("stoic_eln-20260101-120000.db.gz.enc")
    assert a is not None
    assert b is not None
    assert a == b
