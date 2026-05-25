"""Tests for patch 14.0 — database backup service.

Covers: create_backup writes a valid gzipped SQLite that can be
read back, list_backups returns metadata in correct order,
prune_old_backups respects the retention policy, restore_backup
swaps DBs and sidelines the previous live one, settings round-trip
through AppSetting, CLI command works.

These tests use a file-backed SQLite DB (not the default in-memory
one from TestingConfig) because the backup service reads pages off
disk via sqlite3.Connection.backup().
"""

from __future__ import annotations

import gzip
import sqlite3
from datetime import datetime, timedelta

import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db
from stoic_eln.models.settings import AppSetting
from stoic_eln.services import backup as backup_service


@pytest.fixture
def file_app(tmp_path):
    """An app variant whose DB lives on disk under tmp_path.

    The backup service does ``sqlite3.connect(path).backup(...)``,
    which requires an actual file. The default ``app`` fixture
    uses ``:memory:`` and can't be backed up.
    """
    db_path = tmp_path / "stoic_test.db"
    backup_dir = tmp_path / "backups"

    class _FileTestingConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    app = create_app(_FileTestingConfig)
    with app.app_context():
        db.create_all()
        # Point backups at our temp dir so we don't pollute the
        # instance/ folder during tests.
        AppSetting.set("backup.path", str(backup_dir))
        yield app
        db.session.remove()
        db.drop_all()


def _seed_marker(app, value: str = "alpha"):
    """Put one row in app_setting so a backup has something to verify."""
    with app.app_context():
        AppSetting.set("test.marker", value)


def test_create_backup_produces_readable_gzipped_sqlite(file_app, tmp_path):
    """create_backup writes a gzipped file whose contents are a
    valid SQLite DB containing the data from the live DB."""
    _seed_marker(file_app, "alpha")
    with file_app.app_context():
        bf = backup_service.create_backup(reason="test")

        assert bf.path.exists()
        assert bf.path.suffix == ".gz"
        assert bf.size_bytes > 0

        # Decompress and assert we can read our marker.
        decoded = tmp_path / "decoded.db"
        with gzip.open(bf.path, "rb") as r, decoded.open("wb") as w:
            w.write(r.read())

        conn = sqlite3.connect(str(decoded))
        cur = conn.execute(
            "SELECT value FROM app_setting WHERE key=?", ("test.marker",)
        )
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "alpha"


def test_create_backup_filename_format(file_app):
    """Backup filenames follow the stoic_eln-YYYYMMDD-HHMMSS.db.gz
    convention so they sort chronologically."""
    with file_app.app_context():
        bf = backup_service.create_backup(reason="test")
        name = bf.filename
        assert name.startswith("stoic_eln-")
        assert name.endswith(".db.gz")
        ts = backup_service._parse_timestamp(name)
        assert ts is not None
        from stoic_eln.services.backup import _now_utc
        assert abs((_now_utc() - ts).total_seconds()) < 60


def test_list_backups_newest_first(file_app, tmp_path):
    """Listing returns newest first and ignores stray files."""
    with file_app.app_context():
        backup_dir = backup_service.get_backup_dir()

        for ts_str in ("20260101-000000", "20260201-000000", "20260301-000000"):
            (backup_dir / f"stoic_eln-{ts_str}.db.gz").write_bytes(b"stub")
        (backup_dir / "notes.txt").write_text("hello")

        items = backup_service.list_backups()
        names = [b.filename for b in items]
        assert names == [
            "stoic_eln-20260301-000000.db.gz",
            "stoic_eln-20260201-000000.db.gz",
            "stoic_eln-20260101-000000.db.gz",
        ]


def test_prune_keeps_recent_daily_and_weekly(file_app):
    """Retention policy: N daily + M weekly snapshots."""
    with file_app.app_context():
        AppSetting.set("backup.keep_daily", "3")
        AppSetting.set("backup.keep_weekly", "2")

        backup_dir = backup_service.get_backup_dir()
        base = datetime(2026, 4, 30, 12, 0, 0)
        for d in range(30):
            ts = base - timedelta(days=d)
            name = "stoic_eln-" + ts.strftime("%Y%m%d-%H%M%S") + ".db.gz"
            (backup_dir / name).write_bytes(b"stub")

        deleted = backup_service.prune_old_backups()
        remaining = backup_service.list_backups()

        # 3 daily + up to 2 weekly snapshots for distinct earlier
        # ISO weeks; exact count depends on calendar boundaries.
        assert 3 <= len(remaining) <= 5
        kept_names = {b.filename for b in remaining}
        for d in range(3):
            ts = base - timedelta(days=d)
            expected = "stoic_eln-" + ts.strftime("%Y%m%d-%H%M%S") + ".db.gz"
            assert expected in kept_names
        assert len(deleted) > 0
        assert len(deleted) + len(remaining) == 30


def test_restore_swaps_db_and_sidelines_previous(file_app):
    """Restore puts a backup's contents into the live DB path and
    renames the previous live DB with a pre-restore suffix."""
    _seed_marker(file_app, "alpha")
    with file_app.app_context():
        bf = backup_service.create_backup(reason="test")
        live_db = backup_service.get_db_path()

        # Mutate the live DB after the backup.
        AppSetting.set("test.marker", "beta")
        db.session.commit()

        # restore_backup commits + closes the session itself, so
        # we don't need to do anything special here.
        backup_service.restore_backup(bf.filename)

        # Verify by opening a fresh sqlite3 connection straight to
        # the file.
        conn = sqlite3.connect(str(live_db))
        cur = conn.execute(
            "SELECT value FROM app_setting WHERE key=?", ("test.marker",)
        )
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "alpha"

        # A sidelined copy of the previous live DB should now exist.
        sidelined = list(live_db.parent.glob(f"{live_db.stem}.pre-restore-*.db"))
        assert sidelined, "expected a sidelined pre-restore DB"


def test_settings_defaults_and_overrides(file_app):
    """get_settings returns defaults when AppSetting is empty, and
    respects explicit values when set."""
    with file_app.app_context():
        # Wipe any prior backup.* keys so we test pure defaults.
        for k in list(AppSetting.__table__.columns.keys()):
            pass  # noop, just to keep Python happy
        AppSetting.set("backup.enabled", None)
        AppSetting.set("backup.hour", None)
        AppSetting.set("backup.minute", None)
        AppSetting.set("backup.keep_daily", None)
        AppSetting.set("backup.keep_weekly", None)

        s = backup_service.get_settings()
        assert s["enabled"] is True
        assert s["hour"] == 3
        assert s["minute"] == 0
        assert s["keep_daily"] == 30
        assert s["keep_weekly"] == 12

        AppSetting.set("backup.enabled", "0")
        AppSetting.set("backup.hour", "23")
        AppSetting.set("backup.keep_daily", "7")

        s = backup_service.get_settings()
        assert s["enabled"] is False
        assert s["hour"] == 23
        assert s["keep_daily"] == 7
        assert s["minute"] == 0
        assert s["keep_weekly"] == 12


def test_run_scheduled_backup_disabled_returns_none(file_app):
    """When backups are disabled, run_scheduled_backup is a no-op."""
    with file_app.app_context():
        AppSetting.set("backup.enabled", "0")
        backup_dir = backup_service.get_backup_dir()

        result = backup_service.run_scheduled_backup()
        assert result is None
        assert list(backup_dir.glob("*.db.gz")) == []


def test_run_scheduled_backup_enabled_creates_file(file_app):
    """When enabled, run_scheduled_backup creates a backup."""
    with file_app.app_context():
        AppSetting.set("backup.enabled", "1")
        result = backup_service.run_scheduled_backup()
        assert result is not None
        assert result.path.exists()


def test_cli_backup_command(file_app):
    """The `flask backup` CLI command runs end-to-end."""
    runner = file_app.test_cli_runner()
    res = runner.invoke(args=["backup", "--reason", "test"])
    assert res.exit_code == 0, res.output
    assert "Created:" in res.output


def test_parse_timestamp_rejects_invalid():
    """The filename parser is strict: it returns None for anything
    that doesn't match the convention."""
    assert backup_service._parse_timestamp("foo.txt") is None
    assert backup_service._parse_timestamp("stoic_eln-bogus.db.gz") is None
    assert backup_service._parse_timestamp("stoic_eln-20260101-000000.db") is None
    assert backup_service._parse_timestamp(
        "stoic_eln-20260101-120000.db.gz"
    ) is not None

