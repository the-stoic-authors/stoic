"""Tests for the instance directory — where ``backups/``,
``backup.key`` and ``auth_source`` actually live.

Background, from the Raspberry Pi 3B endurance test. Flask computes
``instance_path`` from the package location. In the Docker image the
package is installed into a virtualenv, so the default resolved to
``/opt/venv/var/stoic_eln-instance`` — inside the container's
writable layer, not on any volume. The ``stoic-backups`` volume that
``docker-compose.yml`` dutifully mounted was never written to once.

Consequences, in order of nastiness: ``docker compose up -d`` (the
upgrade step in our own docs) destroyed every nightly backup, and
would have destroyed ``backup.key`` along with them — leaving an
operator holding backups they can no longer decrypt. The failure was
invisible from inside the app, because ``backups-list`` reads the
same wrong directory and happily lists files right up until they
vanish. One install in the field lost its entire backup history to a
single upgrade before this was caught.

The fix is ``STOIC_INSTANCE_PATH`` plus a copy-on-boot migration for
files already sitting at the old location. These tests pin both, and
in particular pin the properties that make the migration safe to run
in every worker at once.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from flask import Flask

from stoic_eln import _migrate_legacy_instance_dir, create_app
from stoic_eln.config import TestingConfig


# ── STOIC_INSTANCE_PATH ────────────────────────────────────────────


def test_env_var_sets_instance_path(tmp_path, monkeypatch):
    """A deployment points the instance dir at persistent storage
    with an environment variable; the factory must honour it."""
    target = tmp_path / "persistent"
    monkeypatch.setenv("STOIC_INSTANCE_PATH", str(target))

    app = create_app(TestingConfig)

    assert Path(app.instance_path) == target


def test_explicit_argument_beats_env_var(tmp_path, monkeypatch):
    """Tests and embedders pass instance_path directly. That must
    win, or the conftest fixture would be silently overridden by a
    stray variable in the developer's shell."""
    monkeypatch.setenv("STOIC_INSTANCE_PATH", str(tmp_path / "from-env"))
    explicit = tmp_path / "from-argument"

    app = create_app(TestingConfig, instance_path=str(explicit))

    assert Path(app.instance_path) == explicit


def test_empty_env_var_falls_back_to_flask_default(tmp_path, monkeypatch):
    """``STOIC_INSTANCE_PATH=`` in a .env file must not resolve to
    the empty string — Flask would treat it as the current working
    directory, which is worse than its own default."""
    monkeypatch.setenv("STOIC_INSTANCE_PATH", "")

    app = create_app(TestingConfig)

    assert Path(app.instance_path) == Path(app.auto_find_instance_path())


# ── The copy-on-boot migration ─────────────────────────────────────


def _app_with(legacy: Path, current: Path) -> Flask:
    """A bare Flask app whose 'default' instance path is *legacy*
    and whose active one is *current*, with TESTING off so the
    migration actually runs."""
    app = Flask("stoic_eln_test", instance_path=str(current))
    app.config["TESTING"] = False
    app.auto_find_instance_path = lambda: str(legacy)  # type: ignore[method-assign]
    return app


@pytest.fixture
def legacy_and_current(tmp_path):
    legacy = tmp_path / "opt-venv-var-instance"
    current = tmp_path / "app-instance"
    (legacy / "backups").mkdir(parents=True)
    current.mkdir()
    (legacy / "auth_source").write_text("file\n")
    (legacy / "backups" / "stoic_eln-20260908-030000.db.gz").write_bytes(b"oldest")
    (legacy / "backups" / "stoic_eln-20260926-030000.db.gz").write_bytes(b"newest")
    return legacy, current


def test_migration_copies_nested_files(legacy_and_current):
    legacy, current = legacy_and_current

    _migrate_legacy_instance_dir(_app_with(legacy, current))

    assert (current / "auth_source").read_text() == "file\n"
    assert (current / "backups" / "stoic_eln-20260908-030000.db.gz").read_bytes() == b"oldest"
    assert (current / "backups" / "stoic_eln-20260926-030000.db.gz").read_bytes() == b"newest"


def test_migration_copies_rather_than_moves(legacy_and_current):
    """A rollback to an older version looks in the old location.
    If we moved the files it would find nothing at all — turning a
    downgrade into a second way of losing the backups."""
    legacy, current = legacy_and_current

    _migrate_legacy_instance_dir(_app_with(legacy, current))

    assert (legacy / "auth_source").is_file()
    assert (legacy / "backups" / "stoic_eln-20260908-030000.db.gz").is_file()


def test_migration_never_overwrites_the_destination(legacy_and_current):
    """The live file always wins. Overwriting it with an older copy
    from the abandoned directory would be data loss committed by the
    very code meant to prevent it."""
    legacy, current = legacy_and_current
    (current / "auth_source").write_text("env\n")

    _migrate_legacy_instance_dir(_app_with(legacy, current))

    assert (current / "auth_source").read_text() == "env\n"


def test_migration_is_idempotent(legacy_and_current):
    """Every gunicorn worker runs the factory, so this executes
    several times at boot, concurrently. Running it twice must be
    indistinguishable from running it once."""
    legacy, current = legacy_and_current
    app = _app_with(legacy, current)

    _migrate_legacy_instance_dir(app)
    (current / "backups" / "stoic_eln-20260908-030000.db.gz").write_bytes(b"touched")
    _migrate_legacy_instance_dir(app)

    assert (current / "backups" / "stoic_eln-20260908-030000.db.gz").read_bytes() == b"touched"


def test_migration_leaves_no_partial_files(legacy_and_current):
    """Copies land via a .partial sibling and an atomic rename, so a
    worker reading concurrently sees a whole file or no file. None of
    the scaffolding may survive the run."""
    legacy, current = legacy_and_current

    _migrate_legacy_instance_dir(_app_with(legacy, current))

    assert not list(current.rglob("*.partial"))


def test_migration_preserves_permissions(legacy_and_current):
    """``backup.key`` is written 0600 because it decrypts every
    backup. A copy that widens it to 0644 would quietly downgrade
    the security of the whole backup chain."""
    legacy, current = legacy_and_current
    key = legacy / "backup.key"
    key.write_text("correct horse battery staple\n")
    key.chmod(0o600)

    _migrate_legacy_instance_dir(_app_with(legacy, current))

    assert (current / "backup.key").stat().st_mode & 0o777 == 0o600


def test_migration_noop_when_paths_match(tmp_path):
    """A normal development install already uses Flask's default.
    There is nothing to migrate and nothing to log."""
    same = tmp_path / "instance"
    same.mkdir()
    (same / "auth_source").write_text("file\n")

    _migrate_legacy_instance_dir(_app_with(same, same))

    assert [p.name for p in same.iterdir()] == ["auth_source"]


def test_migration_noop_when_legacy_absent(tmp_path):
    """A fresh install has no old directory; the migration must stay
    silent rather than create one."""
    legacy = tmp_path / "never-existed"
    current = tmp_path / "instance"
    current.mkdir()

    _migrate_legacy_instance_dir(_app_with(legacy, current))

    assert not legacy.exists()


def test_migration_survives_an_unreadable_legacy_dir(tmp_path):
    """Booting matters more than migrating: the files are still
    readable at the old path and the log says where. A permission
    error here must not take the application down."""
    legacy = tmp_path / "locked"
    current = tmp_path / "instance"
    (legacy / "backups").mkdir(parents=True)
    (legacy / "backups" / "a.db.gz").write_bytes(b"x")
    current.mkdir()
    legacy.chmod(0o000)

    try:
        _migrate_legacy_instance_dir(_app_with(legacy, current))
    finally:
        legacy.chmod(0o755)


@pytest.mark.skipif(
    os.environ.get("STOIC_INSTANCE_PATH") is not None,
    reason="the developer's environment already pins the instance path",
)
def test_migration_skipped_under_testing(legacy_and_current):
    """The suite points every app at an isolated temp directory. If
    the migration ran there it would drag in whatever happens to sit
    in the developer's real instance directory."""
    legacy, current = legacy_and_current
    app = _app_with(legacy, current)
    app.config["TESTING"] = True

    _migrate_legacy_instance_dir(app)

    assert not (current / "auth_source").exists()
