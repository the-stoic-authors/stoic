"""Stoic ELN — Passphrase store with pluggable sources.

Centralises how the application gets the master passphrase used
for backup encryption (14.1) AND live-DB encryption (14.2). One
passphrase, one store, three possible sources:

  - ``prompt``: read from stdin at first access (RAM-only mode —
    the passphrase never touches disk and disappears when the
    process exits). This is the strongest mode against
    "stolen-disk" threat models because there's literally
    nothing on the filesystem an attacker could derive the key
    from.

  - ``file``: read from ``instance/backup.key`` (mode 0600). The
    historical default since 14.1. Convenient — no boot prompt —
    but the key file lives on the encrypted-disk-but-could-be-
    rsynced-elsewhere filesystem.

  - ``env``: read from ``STOIC_BACKUP_PASSPHRASE``. Equivalent
    threat profile to ``file``: lives in the process environment,
    which on Unix is visible to other processes the same user
    runs.

# In-process cache

Once a passphrase has been resolved successfully, it's cached in
a module-level variable for the lifetime of the process. This is
necessary for two reasons:

  - In ``prompt`` mode, we obviously can't ask the user again at
    every DB connection (or every nightly backup the scheduler
    fires). The prompt happens once, at first access, then the
    value is held.

  - SQLCipher requires the key on every new connection. Pulling
    the cached value is O(1).

The cached value lives in normal Python memory. It is, by
definition, exposed to memory-dump attacks on a running Stoic
process. This is intrinsic to symmetric encryption with
on-the-fly cipher operations — there is no implementation in any
language that avoids it. The only mitigation is to keep the
process running only when needed, and exit cleanly when not.

# Setting persistence

The mode itself is stored in ``AppSetting`` under the key
``auth.passphrase_source``. Changes are picked up at next boot
(modes that don't need a prompt) or at next first-access (modes
that do).

# Testing affordance

Tests can inject a passphrase by calling ``set_for_testing()``,
which bypasses both the cache resolution logic AND the source
configuration. The fixture must call ``reset_for_testing()`` in
teardown to avoid leaking state across tests.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# ── Sources ──────────────────────────────────────────────────────


SOURCE_NONE = "none"
SOURCE_PROMPT = "prompt"
SOURCE_FILE = "file"
SOURCE_ENV = "env"
SOURCES = (SOURCE_NONE, SOURCE_PROMPT, SOURCE_FILE, SOURCE_ENV)


# User-visible labels and descriptions for the four passphrase
# sources. Wrapped in flask_babel.lazy_gettext so they're picked up
# by ``pybabel extract`` and translated at request time based on
# the user's locale. The dict names keep the ``_IT`` suffix for
# backward compatibility with existing imports — the actual content
# is locale-aware via lazy_gettext.
from flask_babel import lazy_gettext as _l  # noqa: E402

SOURCE_LABELS_IT = {
    SOURCE_NONE: _l("Nessuna (backup in chiaro, nessun prompt)"),
    SOURCE_PROMPT: _l("Richiesta all'avvio (solo in RAM)"),
    SOURCE_FILE: _l("File instance/backup.key"),
    SOURCE_ENV: _l("Variabile d'ambiente STOIC_BACKUP_PASSPHRASE"),
}
SOURCE_DESCRIPTIONS_IT = {
    SOURCE_NONE: _l(
        "Crittografia disattivata. I backup vengono salvati in chiaro, "
        "il DB live (se cifrato) non parte. Default per chi non ha mai "
        "configurato la crittografia. Da cambiare appena attivi una "
        "delle altre modalità."
    ),
    SOURCE_PROMPT: _l(
        "Massima sicurezza contro furto del disco: la passphrase "
        "non viene mai scritta su disco. Stoic la chiede a ogni "
        "avvio e la tiene solo in RAM. Se Stoic non gira, niente "
        "decifra il DB. Implica: ogni 'make run' richiede una "
        "digitazione; i backup notturni richiedono Stoic acceso."
    ),
    SOURCE_FILE: _l(
        "Comodità massima: la passphrase è in instance/backup.key "
        "(permessi 0600). Stoic la legge automaticamente al boot. "
        "Backup notturni funzionano anche se Stoic non è in uso. "
        "Vulnerabile se l'attaccante prende disco + file di chiave."
    ),
    SOURCE_ENV: _l(
        "Adatta a deployment server (systemd-creds, Docker secrets, "
        "ecc): la passphrase è iniettata via env var prima del "
        "lancio. Equivalente in sicurezza al modo 'file' nella "
        "maggior parte dei casi d'uso desktop."
    ),
}


def current_source() -> str:
    """Return the configured passphrase source.

    Reads in two phases:

      1. **Pre-DB phase** (called from ``_maybe_enable_sqlcipher``
         BEFORE the DB is opened): reads from a small flat file
         ``instance/auth_source`` written by the UI. We can't use
         AppSetting here because the DB itself may be encrypted
         and not yet openable.

      2. **Post-DB phase** (called from any UI/route after Flask
         has started): reads from ``AppSetting.auth.passphrase_source``,
         falling back to the flat file. AppSetting is the source
         of truth for the UI.

    Falls back to ``"prompt"`` if neither has a valid value — the
    secure default for new installs.
    """
    # Try AppSetting first (post-DB phase). If the DB isn't open
    # yet this throws a RuntimeError and we silently fall through.
    try:
        from stoic_eln.models.settings import AppSetting
        from flask import has_app_context
        if has_app_context():
            raw = AppSetting.get("auth.passphrase_source")
            if raw in SOURCES:
                return raw
    except Exception:
        pass

    # Pre-DB phase or fallback: read the filesystem marker.
    raw = _read_source_marker()
    if raw in SOURCES:
        return raw

    return SOURCE_NONE


def _source_marker_path() -> Path | None:
    """Path of the on-disk source marker, or None if no Flask app
    context is available.

    The marker lives at ``<instance>/auth_source``. We can't import
    Flask at module load (circular), so this is a lazy helper.
    """
    try:
        from flask import current_app
        return Path(current_app.instance_path) / "auth_source"
    except Exception:
        return None


def _read_source_marker() -> str | None:
    """Read the source from the filesystem marker, or None if
    unreadable/absent."""
    p = _source_marker_path()
    if p is None or not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_source_marker(source: str) -> None:
    """Write the source to the filesystem marker so the next boot
    can read it pre-DB. Atomic via tmp + rename."""
    p = _source_marker_path()
    if p is None:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(source, encoding="utf-8")
    tmp.replace(p)


def set_source(source: str) -> None:
    """Persist a new passphrase source.

    Writes to both AppSetting (so the UI sees it consistently
    inside the running process) AND the filesystem marker (so
    the next boot reads it before the DB is opened).

    Caller must restart Stoic for the change to fully apply
    (the change of source affects how the DB is opened).
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source!r}")
    try:
        from stoic_eln.models.settings import AppSetting
        AppSetting.set("auth.passphrase_source", source)
    except Exception:
        # Could fail if called from a context where the DB isn't
        # open. The filesystem marker is still authoritative for
        # the next boot.
        pass
    _write_source_marker(source)


def ensure_default_source_setting(instance_path: Path) -> None:
    """Initialise the source marker for a fresh install, OR
    migrate an existing install that already has a ``backup.key``
    file (i.e. came from patch 14.1/14.2).

    Called once at boot. Doesn't overwrite an explicit setting.
    The output is the on-disk marker at ``instance/auth_source``.
    """
    marker = instance_path / "auth_source"
    if marker.exists():
        try:
            cur = marker.read_text(encoding="utf-8").strip()
            if cur in SOURCES:
                return  # already initialised
        except OSError:
            pass

    key_file = instance_path / "backup.key"
    if key_file.exists() and key_file.is_file():
        # Existing install carrying over from 14.1/14.2: respect
        # what the user has on disk rather than forcing a re-prompt.
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(SOURCE_FILE, encoding="utf-8")
        logger.info(
            "Migrated passphrase source to 'file' (existing backup.key found)"
        )
    elif os.environ.get("STOIC_BACKUP_PASSPHRASE"):
        # User has explicitly set the env var: default to env.
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(SOURCE_ENV, encoding="utf-8")
        logger.info(
            "Migrated passphrase source to 'env' (STOIC_BACKUP_PASSPHRASE set)"
        )
    else:
        # Fresh install: encryption off by default. The user
        # opts in explicitly by choosing prompt/file/env from
        # Settings → Backup. This keeps fresh installs working
        # out of the box (plain backups, no boot prompts) and
        # leaves the security upgrade as a conscious decision.
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(SOURCE_NONE, encoding="utf-8")
        logger.info("Initialised passphrase source to 'none' (default)")


# ── In-process cache ─────────────────────────────────────────────


_cached_passphrase: str | None = None
_prompt_callback: Callable[[], str] | None = None


def reset_cache() -> None:
    """Wipe the cached passphrase. Used on logout-style events
    and by the test suite teardown.

    Note: Python doesn't guarantee that the underlying bytes are
    overwritten in memory. This is a best-effort wipe at the
    Python-object level, useful but not bulletproof against
    memory forensics.
    """
    global _cached_passphrase
    if _cached_passphrase is not None:
        # Try to clobber the string in-place. CPython strings are
        # immutable so this doesn't really overwrite the buffer,
        # but it does drop the only reference we hold.
        _cached_passphrase = None


def set_for_testing(passphrase: str) -> None:
    """Inject a passphrase, bypassing the configured source.
    Tests use this to avoid hitting stdin or filesystem."""
    global _cached_passphrase
    _cached_passphrase = passphrase


def reset_for_testing() -> None:
    """Alias of reset_cache; intended for test teardown clarity."""
    reset_cache()


def is_cached() -> bool:
    """True if a passphrase is currently in the in-process cache."""
    return _cached_passphrase is not None


def set_prompt_callback(callback: Callable[[], str] | None) -> None:
    """Override how the ``prompt`` source asks the user.

    Default (``None``): use ``getpass.getpass()`` reading from
    stdin/tty. This is what runs under ``flask run`` / ``make run``.

    Some entry points (CLI subcommands) want to control the prompt
    themselves so they can show a richer banner; they call this
    with a custom callable.
    """
    global _prompt_callback
    _prompt_callback = callback


# ── Resolution ───────────────────────────────────────────────────


def get_passphrase(
    instance_path: Path,
    verifier: Callable[[str], bool] | None = None,
) -> str | None:
    """Return the master passphrase, prompting or reading sources
    as configured.

    Returns ``None`` if the source produces nothing (e.g. ``file``
    source but no file; ``env`` source but no env var). The
    ``prompt`` source raises ``PassphraseUnavailable`` instead of
    returning None when the user can't be prompted (no tty).

    Cached after the first successful resolution. Subsequent
    calls return the cached value with no I/O.

    Args:
        instance_path: Flask instance path (for file lookups).
        verifier: optional callable that takes a candidate
            passphrase and returns True if it's correct. Only
            used in ``prompt`` mode — the user gets up to 3
            attempts to enter a passphrase that the verifier
            accepts. In ``file`` and ``env`` modes the verifier
            is ignored (those sources are trusted).
    """
    global _cached_passphrase
    if _cached_passphrase is not None:
        return _cached_passphrase

    source = current_source()
    pp: str | None = None

    if source == SOURCE_NONE:
        # Encryption disabled: no passphrase, no prompt, ever.
        return None
    elif source == SOURCE_ENV:
        pp = _from_env()
    elif source == SOURCE_FILE:
        pp = _from_file(instance_path)
    elif source == SOURCE_PROMPT:
        pp = _from_prompt(verifier=verifier)
    else:
        # Defensive: marker may have been hand-edited to garbage
        logger.warning("unknown passphrase source %r, treating as 'none'",
                       source)
        return None

    if pp:
        _cached_passphrase = pp
    return pp


def has_passphrase_available(instance_path: Path) -> bool:
    """Predicate version: True if a passphrase is reachable without
    actually prompting the user.

    The ``prompt`` source returns True only if a passphrase is
    already cached (i.e. someone already entered it earlier in
    this process). This is the right semantics for "should we
    encrypt new backups?" checks that mustn't block on stdin.
    """
    if _cached_passphrase is not None:
        return True
    source = current_source()
    if source == SOURCE_NONE:
        return False
    if source == SOURCE_ENV:
        return bool(_from_env())
    if source == SOURCE_FILE:
        return bool(_from_file(instance_path))
    # source == SOURCE_PROMPT: not cached, so no
    return False


class PassphraseUnavailable(RuntimeError):
    """Raised when the configured source can't produce a passphrase.

    Common causes:
      - ``prompt`` mode but no tty (e.g. running under systemd,
        cron, a subprocess without stdin)
      - ``file`` mode but ``instance/backup.key`` doesn't exist
      - ``env`` mode but the env var is unset
    """


# ── Source implementations ───────────────────────────────────────


def _from_env() -> str | None:
    val = os.environ.get("STOIC_BACKUP_PASSPHRASE")
    if val and val.strip():
        return val.strip()
    return None


def _from_file(instance_path: Path) -> str | None:
    key_file = instance_path / "backup.key"
    if not key_file.exists() or not key_file.is_file():
        return None
    try:
        pw = key_file.read_text(encoding="utf-8").strip()
        return pw or None
    except OSError as e:
        logger.warning("could not read %s: %s", key_file, e)
        return None


def _from_prompt(verifier: Callable[[str], bool] | None = None) -> str | None:
    """Read passphrase from terminal, with up to 3 retries.

    If ``verifier`` is provided, each attempt is checked against
    it (typically by trying to open the encrypted DB) and a
    failed attempt loops back to the prompt. Without a verifier,
    any non-empty entry is returned on the first try.

    Returns the entered string, or None if the user aborts (Ctrl-C)
    or runs out of attempts. Raises ``PassphraseUnavailable`` if
    there's no TTY (i.e. boot can't proceed in ``prompt`` mode
    on a headless run).
    """
    if _prompt_callback is not None:
        try:
            pp = _prompt_callback().strip() or None
        except (EOFError, KeyboardInterrupt):
            return None
        if pp and verifier is not None and not verifier(pp):
            return None
        return pp

    if not sys.stdin.isatty():
        raise PassphraseUnavailable(
            "Passphrase mode is 'prompt' but stdin is not a TTY. "
            "Either run Stoic from a terminal, or switch the "
            "passphrase source to 'file' / 'env' from "
            "Settings → Backup."
        )

    import getpass
    try:
        for attempt in range(3):
            if attempt == 0:
                label = "Stoic: enter database passphrase: "
            else:
                label = f"Wrong passphrase, retry ({attempt + 1}/3): "
            pp = getpass.getpass(label)
            if not pp or not pp.strip():
                continue
            pp = pp.strip()
            if verifier is None or verifier(pp):
                return pp
        print("Too many failed attempts.", file=sys.stderr)
        return None
    except (EOFError, KeyboardInterrupt):
        print("", file=sys.stderr)  # clean newline after ^C
        return None
