"""Stoic ELN — Database backup service.

Performs atomic SQLite backups using the ``sqlite3.Connection.backup()``
API, gzips them, and stores them under ``instance/backups/`` (or
wherever ``backup.path`` is configured to point).

Key points:

- **Atomicity**: we use the SQLite online backup API, which copies
  pages while the source DB is being written to. This is safe even
  if the app is mid-transaction. A naive ``cp stoic_eln.db ...``
  could capture a half-written WAL state.
- **Compression**: backups are gzipped (level 6, balanced). For a
  typical Stoic DB at ~10 MB, the gzipped artifact is ~2-3 MB.
- **Naming**: ``stoic_eln-YYYYMMDD-HHMMSS.db.gz`` — sortable
  lexicographically, no parsing needed for chronological listing.
- **Retention**: a 2-tier policy that keeps the last N daily and
  the last M weekly snapshots. Defaults: 30 daily + 12 weekly.
- **Restore**: produces a fresh ``.db`` file from a ``.db.gz`` and
  swaps it in for the live DB. Audit-logged. The previous live DB
  is renamed to ``.pre-restore-YYYYMMDD-HHMMSS.db`` so nothing is
  irrevocably lost.

This module is pure functions; the Flask routes / CLI / scheduler
call into it.
"""

from __future__ import annotations

import gzip
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

from flask import current_app

logger = logging.getLogger(__name__)


# ── Filenames ────────────────────────────────────────────────────

_BACKUP_PREFIX = "stoic_eln-"
_BACKUP_SUFFIX = ".db.gz"
_BACKUP_SUFFIX_ENC = ".db.gz.enc"
_TIMESTAMP_FMT = "%Y%m%d-%H%M%S"


@dataclass(frozen=True)
class BackupFile:
    """Metadata about a single backup file on disk."""

    path: Path
    timestamp: datetime  # naive UTC, derived from filename
    size_bytes: int
    encrypted: bool = False

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _format_timestamp(ts: datetime) -> str:
    return ts.strftime(_TIMESTAMP_FMT)


def _parse_timestamp(name: str) -> datetime | None:
    """Extract the timestamp from a backup filename, or None if
    the name doesn't match our convention. Accepts both unencrypted
    (.db.gz) and encrypted (.db.gz.enc) suffixes."""
    if not name.startswith(_BACKUP_PREFIX):
        return None
    if name.endswith(_BACKUP_SUFFIX_ENC):
        stem = name[len(_BACKUP_PREFIX) : -len(_BACKUP_SUFFIX_ENC)]
    elif name.endswith(_BACKUP_SUFFIX):
        stem = name[len(_BACKUP_PREFIX) : -len(_BACKUP_SUFFIX)]
    else:
        return None
    try:
        return datetime.strptime(stem, _TIMESTAMP_FMT)
    except ValueError:
        return None


def _is_encrypted_filename(name: str) -> bool:
    return name.endswith(_BACKUP_SUFFIX_ENC)


# ── Path resolution ──────────────────────────────────────────────


def get_backup_dir() -> Path:
    """Return the configured backup directory, creating it if needed.

    Reads ``backup.path`` from AppSetting; falls back to
    ``<instance>/backups/`` if not set.
    """
    from stoic_eln.models.settings import AppSetting

    instance_path = Path(current_app.instance_path)
    configured = AppSetting.get("backup.path")
    if configured:
        path = Path(configured)
        # Relative paths are resolved against the instance directory
        # so a config of "backups" stays portable across machines.
        if not path.is_absolute():
            path = instance_path / path
    else:
        path = instance_path / "backups"

    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    """Return the path to the live SQLite DB file.

    Resolves from ``SQLALCHEMY_DATABASE_URI`` (``sqlite:///...``).
    Raises if the URI isn't SQLite — Stoic targets SQLite only.
    """
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        raise RuntimeError(f"backup service only supports SQLite, got: {uri}")
    return Path(uri[len("sqlite:///") :])


# ── Settings helpers ─────────────────────────────────────────────


def get_settings() -> dict:
    """Return all backup-related settings with their effective values."""
    from stoic_eln.models.settings import AppSetting

    def _int(key: str, default: int) -> int:
        v = AppSetting.get(key)
        try:
            return int(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def _bool(key: str, default: bool) -> bool:
        v = AppSetting.get(key)
        if v is None:
            return default
        return v.lower() in ("1", "true", "yes", "on")

    return {
        "enabled": _bool("backup.enabled", True),
        "path": AppSetting.get("backup.path") or "backups",
        "hour": _int("backup.hour", 3),         # 03:00 local time
        "minute": _int("backup.minute", 0),
        "keep_daily": _int("backup.keep_daily", 30),
        "keep_weekly": _int("backup.keep_weekly", 12),
        "encryption_enabled": encryption_enabled(),
    }


def encryption_enabled() -> bool:
    """True if a passphrase is configured (via env or instance/backup.key).

    When True, new backups are AES-GCM encrypted before being written
    to disk. When False, backups are written as plain gzipped SQLite
    (legacy behaviour from patch 14.0).
    """
    from stoic_eln.services import backup_crypto
    return backup_crypto.has_passphrase(Path(current_app.instance_path))


def _get_passphrase() -> str | None:
    """Look up the configured passphrase, or None if not set."""
    from stoic_eln.services import backup_crypto
    return backup_crypto.resolve_passphrase(Path(current_app.instance_path))


# ── Core operations ──────────────────────────────────────────────


def create_backup(reason: str = "manual") -> BackupFile:
    """Run an atomic, gzipped (and optionally encrypted) backup of
    the live DB.

    Encryption: if a passphrase is configured (via env var or
    ``instance/backup.key``), the gzipped blob is encrypted with
    AES-256-GCM and the resulting file gets a ``.db.gz.enc``
    suffix. Otherwise it's written as plain ``.db.gz`` (the
    behaviour from patch 14.0).

    Args:
        reason: free-form tag stored in the audit log. Typical
            values: ``"manual"``, ``"scheduled"``, ``"pre-restore"``.

    Returns:
        BackupFile describing the artifact written to disk.
    """
    from stoic_eln.services.audit import log_event

    src = get_db_path()
    if not src.exists():
        raise FileNotFoundError(f"Live DB not found at {src}")

    backup_dir = get_backup_dir()
    ts = _now_utc()
    stem = f"{_BACKUP_PREFIX}{_format_timestamp(ts)}"
    raw_path = backup_dir / f"{stem}.db"      # uncompressed tmp
    gz_path = backup_dir / f"{stem}{_BACKUP_SUFFIX}"  # intermediate

    passphrase = _get_passphrase()
    encrypted = passphrase is not None
    final_path = (
        backup_dir / f"{stem}{_BACKUP_SUFFIX_ENC}"
        if encrypted
        else gz_path
    )

    # SQLite online backup: copies pages while readers/writers
    # carry on. Safer than `cp` for live DBs with WAL mode.
    #
    # If the live DB is SQLCipher-encrypted (patch 14.2), we use
    # ``sqlcipher_export`` instead of ``Connection.backup()``.
    # The export decrypts pages on the fly and writes them to a
    # plain SQLite file at the destination — exactly what we want:
    # the backup file is portable (readable with plain sqlite3,
    # subject to the 14.1 envelope encryption applied below).
    from stoic_eln.services import db_crypto
    src_is_encrypted = db_crypto.is_encrypted_db(src)
    if src_is_encrypted:
        live_passphrase = _get_passphrase()
        if live_passphrase is None:
            raise RuntimeError(
                "Live DB is SQLCipher-encrypted but no passphrase is "
                "configured; cannot back up. Set STOIC_BACKUP_PASSPHRASE "
                "or create instance/backup.key."
            )
        if not db_crypto.is_sqlcipher_available():
            raise RuntimeError(
                "Live DB is encrypted but sqlcipher3 is not installed."
            )
        import sqlcipher3
        src_conn = sqlcipher3.connect(str(src))
        try:
            safe = live_passphrase.replace("'", "''")
            src_conn.execute(f"PRAGMA key='{safe}'")
            # ATTACH the destination with empty KEY = plain output.
            # sqlcipher_export then writes plain pages there.
            src_conn.execute(
                f"ATTACH DATABASE '{raw_path}' AS plain KEY ''"
            )
            src_conn.execute("SELECT sqlcipher_export('plain')")
            src_conn.execute("DETACH DATABASE plain")
        finally:
            src_conn.close()
    else:
        # Plain → plain: use the standard online backup API.
        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(raw_path))
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

    # Gzip the dump, then drop the raw file.
    try:
        with raw_path.open("rb") as r, gzip.open(gz_path, "wb", compresslevel=6) as w:
            shutil.copyfileobj(r, w, length=1024 * 1024)
    finally:
        raw_path.unlink(missing_ok=True)

    # Optional: encrypt the gzipped blob in-place.
    if encrypted:
        from stoic_eln.services import backup_crypto
        try:
            plaintext = gz_path.read_bytes()
            ciphertext = backup_crypto.encrypt_bytes(plaintext, passphrase)
            # Write atomically: tmp + rename, so a crash mid-encrypt
            # doesn't leave a half-written .enc file.
            tmp = final_path.with_suffix(final_path.suffix + ".tmp")
            tmp.write_bytes(ciphertext)
            tmp.replace(final_path)
        finally:
            # Always remove the unencrypted .gz, even on failure —
            # we don't want a plaintext backup left lying around
            # when encryption was supposed to be applied.
            gz_path.unlink(missing_ok=True)

    size = final_path.stat().st_size
    log_event(
        action="create_backup",
        entity_type="backup",
        entity_id=0,
        details={
            "filename": final_path.name,
            "size_bytes": size,
            "reason": reason,
            "encrypted": encrypted,
        },
    )
    logger.info(
        "backup created: %s (%.2f MB, reason=%s, encrypted=%s)",
        final_path.name, size / (1024 * 1024), reason, encrypted,
    )

    return BackupFile(
        path=final_path, timestamp=ts, size_bytes=size, encrypted=encrypted,
    )


def list_backups() -> list[BackupFile]:
    """Return all backups in the backup dir, newest first.

    Includes both encrypted (.db.gz.enc) and unencrypted (.db.gz)
    files. The ``encrypted`` flag on each ``BackupFile`` tells you
    which is which.
    """
    backup_dir = get_backup_dir()
    out: list[BackupFile] = []
    for p in backup_dir.iterdir():
        if not p.is_file():
            continue
        ts = _parse_timestamp(p.name)
        if ts is None:
            continue  # not one of ours, ignore
        out.append(BackupFile(
            path=p,
            timestamp=ts,
            size_bytes=p.stat().st_size,
            encrypted=_is_encrypted_filename(p.name),
        ))
    out.sort(key=lambda b: b.timestamp, reverse=True)
    return out


def restore_backup(filename: str) -> Path:
    """Restore the live DB from a backup file.

    The previous live DB is renamed to
    ``<live>.pre-restore-YYYYMMDD-HHMMSS.db`` (kept in the same dir
    as the live DB) so the operation is not destructive — if the
    restore turns out to have been a mistake, the operator can
    rename it back.

    Args:
        filename: bare filename, must exist in the backup dir.

    Returns:
        Path of the new live DB (same as the previous live DB path).

    Important: this function logs the restore event **before**
    swapping files, then commits. After the rename, the SQLAlchemy
    session is still pointed at the now-renamed file (held open by
    the file descriptor on Unix; effectively broken on Windows),
    so a write attempt afterwards would fail. Logging up front
    means the audit trail captures the intent even if the restore
    itself errors out partway through.
    """
    from stoic_eln.services.audit import log_event

    backup_dir = get_backup_dir()
    src = backup_dir / filename
    if not src.exists():
        raise FileNotFoundError(f"Backup not found: {src}")
    ts = _parse_timestamp(filename)
    if ts is None:
        raise ValueError(f"Filename doesn't look like a Stoic backup: {filename}")

    live_db = get_db_path()
    sidelined_name = (
        f"{live_db.stem}.pre-restore-{_format_timestamp(_now_utc())}.db"
    )

    # Log + commit BEFORE touching the DB file. After the swap the
    # session is detached and we can't write the audit row anymore.
    log_event(
        action="restore_backup",
        entity_type="backup",
        entity_id=0,
        details={"filename": filename, "sidelined_live": sidelined_name},
    )
    from stoic_eln.extensions import db as _db
    _db.session.commit()
    # Close the SQLAlchemy session and dispose the engine pool so
    # the file isn't held open while we rename/overwrite it.
    _db.session.close()
    _db.engine.dispose()

    sidelined = None
    if live_db.exists():
        sidelined = live_db.with_name(sidelined_name)
        live_db.rename(sidelined)
        logger.info("sidelined live DB → %s", sidelined.name)

    # Remember whether the previous live DB was encrypted, so we
    # can re-encrypt the restored file to keep configuration
    # consistent across the restore. Without this, restoring on a
    # SQLCipher-protected deployment would silently leave the
    # system with a plain DB — a major regression in protection.
    from stoic_eln.services import db_crypto as _db_crypto
    previous_was_encrypted = (
        sidelined is not None and _db_crypto.is_encrypted_db(sidelined)
    )

    # Decompress (and decrypt if needed) backup into the live DB
    # path. For encrypted backups we must have a passphrase
    # configured — the same one used to create the file.
    if _is_encrypted_filename(filename):
        passphrase = _get_passphrase()
        if passphrase is None:
            # Restore: undo the rename so we don't leave the system
            # in a broken state, then raise.
            if sidelined is not None:
                sidelined.rename(live_db)
            raise RuntimeError(
                "Backup is encrypted but no passphrase is configured "
                "(set STOIC_BACKUP_PASSPHRASE or create instance/backup.key). "
                "Cannot restore."
            )
        from stoic_eln.services import backup_crypto
        encrypted_blob = src.read_bytes()
        try:
            plaintext = backup_crypto.decrypt_bytes(encrypted_blob, passphrase)
        except Exception as e:
            if sidelined is not None:
                sidelined.rename(live_db)
            raise RuntimeError(
                f"Cannot decrypt backup: {e}. Wrong passphrase or "
                f"corrupted file."
            ) from e
        # The decrypted plaintext is itself the gzipped SQLite dump.
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(plaintext), mode="rb") as r, \
             live_db.open("wb") as w:
            shutil.copyfileobj(r, w, length=1024 * 1024)
    else:
        # Legacy plain .db.gz: just decompress.
        with gzip.open(src, "rb") as r, live_db.open("wb") as w:
            shutil.copyfileobj(r, w, length=1024 * 1024)

    # Restore consistency check: if the previous live DB was
    # SQLCipher-encrypted, re-encrypt the just-restored plain file
    # so the deployment stays encrypted across restore operations.
    if previous_was_encrypted:
        live_passphrase = _get_passphrase()
        if live_passphrase is None:
            logger.warning(
                "Previous live DB was encrypted but no passphrase is "
                "configured; restored file is left plain. Set the "
                "passphrase and run 'flask db-encrypt' before restarting."
            )
        elif not _db_crypto.is_sqlcipher_available():
            logger.warning(
                "Previous live DB was encrypted but sqlcipher3 is not "
                "installed; restored file is left plain."
            )
        else:
            result = _db_crypto.encrypt_db(live_db, live_passphrase)
            if not result.ok:
                logger.error(
                    "Restored file could not be re-encrypted: %s. "
                    "The restore completed but the DB is now in plain "
                    "form. Restart Stoic and run 'flask db-encrypt' "
                    "manually.",
                    result.error,
                )
            else:
                # The encrypt_db function sidelines another file, but
                # we don't need it (it's our just-restored plain
                # version). Clean it up to avoid clutter.
                if result.sidelined_path and result.sidelined_path.exists():
                    try:
                        result.sidelined_path.unlink()
                    except OSError:
                        pass
                logger.info("restored DB re-encrypted in place")

    logger.warning("DB restored from %s (sidelined: %s)",
                   filename, sidelined.name if sidelined else "<none>")
    return live_db


def prune_old_backups() -> list[str]:
    """Apply retention policy: keep the N most recent daily backups
    and one per week for the M most recent weeks.

    Returns the list of deleted filenames.
    """
    settings = get_settings()
    keep_daily = settings["keep_daily"]
    keep_weekly = settings["keep_weekly"]

    backups = list_backups()  # newest first
    keep_paths: set[Path] = set()

    # Tier 1: last N daily snapshots, one per calendar day.
    # We pick the newest backup of each distinct day, walking
    # from newest to oldest until we have N days.
    seen_days: list[str] = []
    for b in backups:
        day = b.timestamp.strftime("%Y%m%d")
        if day not in seen_days:
            seen_days.append(day)
            keep_paths.add(b.path)
            if len(seen_days) >= keep_daily:
                break

    # Tier 2: one per ISO week for the M most recent weeks.
    seen_weeks: list[tuple[int, int]] = []
    for b in backups:
        iso_year, iso_week, _ = b.timestamp.isocalendar()
        wk = (iso_year, iso_week)
        if wk not in seen_weeks:
            seen_weeks.append(wk)
            keep_paths.add(b.path)
            if len(seen_weeks) >= keep_weekly:
                break

    deleted: list[str] = []
    for b in backups:
        if b.path not in keep_paths:
            try:
                b.path.unlink()
                deleted.append(b.filename)
                logger.info("pruned backup: %s", b.filename)
            except OSError as e:
                logger.warning("failed to prune %s: %s", b.filename, e)

    return deleted


def run_scheduled_backup() -> BackupFile | None:
    """Wrapper used by the scheduler: create + prune, swallowing
    exceptions so a failed backup never crashes the scheduler.

    Returns the new BackupFile, or None if backups are disabled
    or an error occurred.
    """
    try:
        settings = get_settings()
    except Exception as e:  # config DB not ready, etc.
        logger.error("backup settings unreadable: %s", e)
        return None

    if not settings["enabled"]:
        logger.debug("scheduled backup skipped: disabled")
        return None

    try:
        bf = create_backup(reason="scheduled")
        prune_old_backups()
        return bf
    except Exception as e:
        logger.exception("scheduled backup failed: %s", e)
        return None
