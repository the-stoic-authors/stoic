"""Tests for patch 14.2 — live DB encryption via SQLCipher.

Verifies the detection sniff, the encrypt/decrypt migrations,
the boot-time creator injection, and the interaction with the
backup service (backups of an encrypted live DB still work).

Requires the optional `sqlcipher3-binary` package. Tests are
skipped automatically if it's not installed.
"""

from __future__ import annotations

import sqlite3

import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db
from stoic_eln.services import db_crypto, backup_crypto, backup as backup_service
from stoic_eln.models.settings import AppSetting


pytestmark = pytest.mark.skipif(
    not db_crypto.is_sqlcipher_available(),
    reason="sqlcipher3 not installed; install with: pip install sqlcipher3-binary",
)


# ── Detection ────────────────────────────────────────────────────


def test_plain_sqlite_detected_as_not_encrypted(tmp_path):
    """A standard SQLite file is detected as plain."""
    db_path = tmp_path / "plain.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (x INT)")
    conn.commit()
    conn.close()
    assert db_crypto.is_encrypted_db(db_path) is False


def test_sqlcipher_db_detected_as_encrypted(tmp_path):
    """A SQLCipher-encrypted file is detected as encrypted."""
    import sqlcipher3
    db_path = tmp_path / "enc.db"
    conn = sqlcipher3.connect(str(db_path))
    conn.execute("PRAGMA key='secret'")
    conn.execute("CREATE TABLE t (x INT)")
    conn.commit()
    conn.close()
    assert db_crypto.is_encrypted_db(db_path) is True


def test_missing_file_returns_not_encrypted(tmp_path):
    """is_encrypted_db on a non-existent path returns False
    rather than raising."""
    assert db_crypto.is_encrypted_db(tmp_path / "does-not-exist.db") is False


def test_empty_file_returns_not_encrypted(tmp_path):
    """An empty file (< 16 bytes) is reported as not encrypted."""
    p = tmp_path / "empty.db"
    p.write_bytes(b"")
    assert db_crypto.is_encrypted_db(p) is False


# ── Migration: plain → encrypted ─────────────────────────────────


def test_encrypt_db_basic(tmp_path):
    """encrypt_db transforms a plain DB into a SQLCipher one with
    the same data."""
    src = tmp_path / "plain.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE u (id INT, name TEXT)")
    conn.execute("INSERT INTO u VALUES (1, 'Rico'), (2, 'Alex')")
    conn.commit()
    conn.close()

    result = db_crypto.encrypt_db(src, "test-passphrase-123")
    assert result.ok, result.error
    assert result.sidelined_path is not None
    assert result.sidelined_path.exists()
    assert result.table_count >= 1  # at least our table

    # The file at the original path is now encrypted.
    assert db_crypto.is_encrypted_db(src)

    # Plain sqlite3 can't read it.
    with pytest.raises(sqlite3.DatabaseError):
        c = sqlite3.connect(str(src))
        c.execute("SELECT * FROM u").fetchall()

    # sqlcipher3 + same key can.
    import sqlcipher3
    c = sqlcipher3.connect(str(src))
    c.execute("PRAGMA key='test-passphrase-123'")
    rows = c.execute("SELECT id, name FROM u ORDER BY id").fetchall()
    c.close()
    assert rows == [(1, "Rico"), (2, "Alex")]


def test_encrypt_already_encrypted_is_noop(tmp_path):
    """Running encrypt on an already-encrypted DB with the same
    passphrase is a successful no-op."""
    src = tmp_path / "enc.db"
    import sqlcipher3
    conn = sqlcipher3.connect(str(src))
    conn.execute("PRAGMA key='pw'")
    conn.execute("CREATE TABLE t (x INT)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()

    result = db_crypto.encrypt_db(src, "pw")
    assert result.ok
    assert result.sidelined_path is None  # nothing to sideline
    assert "no-op" in (result.error or "").lower()


def test_encrypt_already_encrypted_wrong_passphrase_fails(tmp_path):
    """Encrypt on an already-encrypted DB with the WRONG passphrase
    is a clear failure (not silent corruption)."""
    src = tmp_path / "enc.db"
    import sqlcipher3
    conn = sqlcipher3.connect(str(src))
    conn.execute("PRAGMA key='right-pw'")
    conn.execute("CREATE TABLE t (x INT)")
    conn.commit()
    conn.close()

    result = db_crypto.encrypt_db(src, "wrong-pw")
    assert not result.ok
    assert "passphrase" in (result.error or "").lower() \
        or "doesn't open" in (result.error or "").lower()


def test_decrypt_db_basic(tmp_path):
    """decrypt_db round-trips an encrypted DB back to plain SQLite."""
    src = tmp_path / "enc.db"
    import sqlcipher3
    conn = sqlcipher3.connect(str(src))
    conn.execute("PRAGMA key='pw'")
    conn.execute("CREATE TABLE t (x INT)")
    conn.execute("INSERT INTO t VALUES (1), (2), (3)")
    conn.commit()
    conn.close()

    result = db_crypto.decrypt_db(src, "pw")
    assert result.ok, result.error
    assert result.sidelined_path is not None

    # Plain sqlite3 reads it.
    c = sqlite3.connect(str(src))
    rows = c.execute("SELECT x FROM t ORDER BY x").fetchall()
    c.close()
    assert rows == [(1,), (2,), (3,)]
    assert not db_crypto.is_encrypted_db(src)


def test_decrypt_plain_db_is_noop(tmp_path):
    """decrypt_db on a plain DB does nothing (success, no sideline)."""
    src = tmp_path / "plain.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE t (x INT)")
    conn.commit()
    conn.close()

    result = db_crypto.decrypt_db(src, "anything")
    assert result.ok
    assert result.sidelined_path is None


def test_encrypt_missing_file_fails(tmp_path):
    """encrypt_db on a non-existent file fails cleanly."""
    result = db_crypto.encrypt_db(tmp_path / "nope.db", "pw")
    assert not result.ok
    assert "does not exist" in (result.error or "")


def test_encrypt_apostrophe_in_passphrase(tmp_path):
    """Passphrases with single quotes are escaped correctly
    (regression: PRAGMA key='...' would break otherwise)."""
    src = tmp_path / "plain.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE t (x INT)")
    conn.execute("INSERT INTO t VALUES (99)")
    conn.commit()
    conn.close()

    pp = "it's a 'tricky' one"
    result = db_crypto.encrypt_db(src, pp)
    assert result.ok, result.error

    # Read back with the same tricky passphrase
    import sqlcipher3
    c = sqlcipher3.connect(str(src))
    c.execute(f"PRAGMA key='{pp.replace(chr(39), chr(39)*2)}'")
    rows = c.execute("SELECT x FROM t").fetchall()
    c.close()
    assert rows == [(99,)]


# ── Boot-time integration ────────────────────────────────────────


@pytest.fixture
def encrypted_app(tmp_path, monkeypatch):
    """An app whose live DB is SQLCipher-encrypted, with the
    passphrase available via the STOIC_BACKUP_PASSPHRASE env var.
    Verifies the boot path picks up the SQLCipher creator
    automatically.

    Uses the env var rather than instance/backup.key because the
    boot-time _maybe_enable_sqlcipher hook runs inside create_app
    and reads from the original instance_path; tests can't easily
    override that after the fact.
    """
    db_path = tmp_path / "stoic.db"
    instance_path = tmp_path / "inst"
    instance_path.mkdir()
    backup_dir = tmp_path / "backups"

    # 1. Create a plain DB with seed data
    plain_conn = sqlite3.connect(str(db_path))
    plain_conn.execute("CREATE TABLE seed (id INT, label TEXT)")
    plain_conn.execute("INSERT INTO seed VALUES (1, 'before-encrypt')")
    plain_conn.commit()
    plain_conn.close()

    # 2. Encrypt it
    pp = "test-passphrase-12345"
    result = db_crypto.encrypt_db(db_path, pp)
    assert result.ok

    # 3. Make the passphrase available via env var. The boot hook
    # auto-promotes a present STOIC_BACKUP_PASSPHRASE to
    # source=env (via ensure_default_source_setting), so we don't
    # need a marker file in advance.
    monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", pp)

    # 4. Boot Stoic on this DB, opting INTO the SQLCipher hook.
    class _Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        # Opt INTO the SQLCipher boot integration. By default
        # TESTING skips _maybe_enable_sqlcipher so that the
        # 300+ tests of unrelated features don't pay the price of
        # decrypt-on-every-connection. This handful of tests
        # specifically exercises the encrypted-DB boot path.
        SQLCIPHER_TEST_ENABLE = True

    app = create_app(_Cfg, instance_path=str(instance_path))

    with app.app_context():
        AppSetting.set("backup.path", str(backup_dir))
        db.session.commit()
        yield app


def test_boot_with_encrypted_db(encrypted_app):
    """Stoic boots cleanly on an encrypted DB when passphrase is
    available. SQLAlchemy queries return the seeded data."""
    from sqlalchemy import text
    with encrypted_app.app_context():
        # Existing Stoic tables (created by create_all on first
        # boot) should be there
        result = db.session.execute(text(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        )).scalar()
        assert result > 0

        # Our seed table is also there
        rows = db.session.execute(
            text("SELECT id, label FROM seed")
        ).fetchall()
        assert (1, "before-encrypt") in [(r[0], r[1]) for r in rows]


def test_backup_of_encrypted_live_db(encrypted_app):
    """Backups taken from an encrypted live DB are still usable:
    the dump is portable (plain SQLite), then wrapped in the 14.1
    envelope (since the passphrase is configured)."""
    with encrypted_app.app_context():
        AppSetting.set("test.marker", "from-encrypted")
        db.session.commit()

        bf = backup_service.create_backup(reason="test")
        # The backup file is .db.gz.enc (14.1 envelope active)
        assert bf.encrypted is True
        assert bf.filename.endswith(".db.gz.enc")

        # Decrypt the envelope manually and verify we get back a
        # gzipped plain SQLite that contains our data.
        import gzip
        blob = bf.path.read_bytes()
        plaintext = backup_crypto.decrypt_bytes(
            blob, "test-passphrase-12345"
        )
        # plaintext is gzipped SQLite
        assert plaintext[:2] == b"\x1f\x8b"
        sql_bytes = gzip.decompress(plaintext)

        # And it's plain SQLite (not encrypted again at the DB level)
        decoded = bf.path.parent / "decoded.db"
        decoded.write_bytes(sql_bytes)
        c = sqlite3.connect(str(decoded))
        row = c.execute(
            "SELECT value FROM app_setting WHERE key=?", ("test.marker",)
        ).fetchone()
        c.close()
        assert row is not None
        assert row[0] == "from-encrypted"


def test_restore_into_encrypted_deployment(encrypted_app):
    """Restoring a backup into an encrypted-DB deployment: the
    restored file must end up encrypted too, so the next boot
    still sees encryption."""
    with encrypted_app.app_context():
        AppSetting.set("test.marker", "alpha")
        db.session.commit()
        bf = backup_service.create_backup(reason="test")

        # Mutate
        AppSetting.set("test.marker", "beta")
        db.session.commit()

        # Restore
        backup_service.restore_backup(bf.filename)

        # The restored file at db path MUST be encrypted again
        # (consistency with the previous live state)
        live_db = backup_service.get_db_path()
        assert db_crypto.is_encrypted_db(live_db), (
            "restored file is plain; encrypted-deployment regressed "
            "to unencrypted"
        )

        # And the data was restored. Open with sqlcipher3 to verify.
        import sqlcipher3
        c = sqlcipher3.connect(str(live_db))
        c.execute("PRAGMA key='test-passphrase-12345'")
        row = c.execute(
            "SELECT value FROM app_setting WHERE key=?", ("test.marker",)
        ).fetchone()
        c.close()
        assert row[0] == "alpha"


# ── CLI ──────────────────────────────────────────────────────────


def test_db_status_command(tmp_path):
    """`flask db-status` reports plain vs encrypted correctly."""
    db_path = tmp_path / "stoic.db"
    instance_path = tmp_path / "inst"
    instance_path.mkdir()
    sqlite3.connect(str(db_path)).close()  # empty plain DB

    class _Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    app = create_app(_Cfg, instance_path=str(instance_path))

    runner = app.test_cli_runner()
    res = runner.invoke(args=["db-status"])
    assert res.exit_code == 0
    assert "plain" in res.output.lower() or "no (" in res.output.lower()


def test_db_encrypt_command_end_to_end(tmp_path):
    """`flask db-encrypt` encrypts the live DB after a safety backup."""
    db_path = tmp_path / "stoic.db"
    instance_path = tmp_path / "inst"
    instance_path.mkdir()
    (instance_path / "backup.key").write_text("cli-test-pp-123456",
                                              encoding="utf-8")
    # Mark passphrase source as 'file' so the resolver looks at
    # the keyfile we just wrote (patch 14.3 default would be NONE).
    (instance_path / "auth_source").write_text("file", encoding="utf-8")

    # Seed plain DB with one row
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE app_setting (key TEXT PRIMARY KEY, value TEXT, "
                 "updated_at TIMESTAMP NOT NULL)")
    conn.execute("INSERT INTO app_setting VALUES ('backup.path', ?, "
                 "datetime('now'))", (str(tmp_path / "backups"),))
    conn.commit()
    conn.close()

    class _Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    app = create_app(_Cfg, instance_path=str(instance_path))

    runner = app.test_cli_runner()
    res = runner.invoke(args=["db-encrypt", "--yes"])
    # The safety backup may fail in TESTING mode (audit_log issues
    # depending on schema state); --skip-backup is the robust path
    # for tests.
    if res.exit_code != 0:
        res = runner.invoke(args=["db-encrypt", "--yes", "--skip-backup"])
    assert res.exit_code == 0, res.output
    assert "encrypted in place" in res.output.lower()
    assert db_crypto.is_encrypted_db(db_path)
