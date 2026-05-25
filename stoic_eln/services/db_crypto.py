"""Stoic ELN — Live database encryption via SQLCipher.

Cifra il file ``instance/stoic_eln.db`` trasparentemente per
l'applicazione: le query SQL funzionano identiche, ma il file
su disco è opaco (AES-256-CBC con HMAC-SHA512 a livello pagina,
default SQLCipher 4). Chi apre il file con ``sqlite3`` standard
vede garbage.

# Architettura

SQLCipher è un drop-in replacement del binding ``sqlite3``: stessa
API, ma supporta ``PRAGMA key`` per fornire la passphrase. Il
binary build ``sqlcipher3-wheels`` contiene SQLCipher 4 statico,
quindi non serve installare la libreria di sistema.

L'integrazione con SQLAlchemy avviene via il parametro ``creator``:
quando Flask-SQLAlchemy crea l'engine, gli passiamo una factory
che apre la connessione con sqlcipher3 e applica subito
``PRAGMA key``.

Stoic decide se usare SQLCipher al boot in base a:

  1. Esistenza della passphrase (env var ``STOIC_BACKUP_PASSPHRASE``
     o file ``instance/backup.key``) — riusa la stessa della 14.1
  2. Sniff dei primi 16 bytes del file: ``"SQLite format 3\x00"`` =
     plain, qualunque altra cosa = SQLCipher

Questo permette transizioni senza configurazione: applicare la
patch su un DB plain non rompe nulla; il DB viene letto in chiaro
finché non lanci ``flask db-encrypt``.

# Migrazione

``flask db-encrypt`` esegue:

  1. Verifica che la passphrase sia configurata
  2. Crea un backup di safety (riusa il backup service 14.0/14.1)
  3. Esporta il DB con ``ATTACH DATABASE … KEY '...' AS encrypted``
     + ``SELECT sqlcipher_export('encrypted')`` (operazione atomica
     di SQLCipher)
  4. Verifica il nuovo file aprendolo e contando le tabelle
  5. Rinomina l'originale in ``.pre-encrypt-…`` (sidelined,
     recuperabile)
  6. Rinomina il nuovo file al posto dell'originale

Tutto idempotente: lanciare ``db-encrypt`` su un DB già cifrato è
un no-op (con messaggio chiaro).

``flask db-decrypt`` fa l'inverso, per chi vuole tornare a un DB
plain (rare, ma supportato).

# Reload

Cambiare la cifratura del live DB **richiede un restart di Stoic**
perché l'engine SQLAlchemy va ricreato con il nuovo ``creator``.
La CLI fa la migrazione mentre Stoic non gira (ipotesi: l'admin
ferma il server, lancia ``db-encrypt``, riavvia). Se Stoic gira
durante la migrazione il file ``.db`` è bloccato dal WAL e
``sqlcipher_export`` fallirebbe — meglio così, l'admin se ne
accorge subito invece di trovarsi un DB corrotto.

# Limitazioni note

- **La passphrase è in RAM** durante l'esecuzione. Non c'è modo
  di evitarlo: SQLCipher chiede di passargliela ad ogni
  connessione. Un memory dump del processo Stoic la rivela.
- **Live DB cifrato + backup ulteriormente cifrato (14.1)** =
  doppia cifratura. Wasteful sui cicli CPU (~250ms in più per
  backup), ma backup portabili: anche se SQLCipher venisse
  rimosso domani, il backup file resta apribile con la
  passphrase tramite il restore della 14.1, che poi richiede
  SQLCipher per aprire il DB risultante. Trade-off accettabile.
- **Il backup service usa sqlite3.Connection.backup()** per la
  copia online. Funziona anche con SQLCipher purché entrambe le
  connessioni siano sqlcipher3 e abbiano la stessa key.
  Patch 14.1 va aggiornata in conseguenza (vedi modifica a
  ``backup.create_backup``).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from datetime import UTC

logger = logging.getLogger(__name__)


# ── Detection ────────────────────────────────────────────────────

# A plain SQLite file always starts with this exact 16-byte string.
# SQLCipher encrypts every page including the first, so the magic
# header is also encrypted — the file starts with random-looking
# bytes from the crypto layer.
_PLAIN_SQLITE_MAGIC = b"SQLite format 3\x00"


def is_encrypted_db(path: Path) -> bool:
    """True if the given .db file looks SQLCipher-encrypted.

    Heuristic: any SQLite file that doesn't start with the standard
    plain-text header magic is treated as encrypted. This is
    extremely robust because plain SQLite files *always* start
    with that exact byte sequence (it's required by the format
    spec).

    For empty/missing files, returns False (so callers default to
    "use plain sqlite for first access").
    """
    if not path.exists() or path.stat().st_size < 16:
        return False
    with path.open("rb") as f:
        header = f.read(16)
    return header != _PLAIN_SQLITE_MAGIC


def is_sqlcipher_available() -> bool:
    """True if the sqlcipher3 binding can be imported.

    Used to fall back gracefully when the package isn't installed:
    Stoic still works on a plain DB, but db-encrypt is unavailable.
    """
    try:
        import sqlcipher3  # noqa: F401

        return True
    except ImportError:
        return False


# ── Connection factory ───────────────────────────────────────────


def make_sqlcipher_creator(db_path: str, passphrase: str):
    """Build a SQLAlchemy ``creator`` callable that opens
    sqlcipher3 connections to ``db_path`` and applies PRAGMA key.

    Flask-SQLAlchemy uses this via ``SQLALCHEMY_ENGINE_OPTIONS``.

    SQLCipher 4 defaults (PBKDF2-HMAC-SHA512 with 256000 iterations,
    AES-256-CBC, 4096-byte page) are conservative and modern; we
    don't override them. If you ever need to read backups created
    by SQLCipher 3 binaries, set the compatibility pragma after
    PRAGMA key (e.g. ``PRAGMA cipher_compatibility = 3``).
    """
    import sqlcipher3

    def _connect():
        conn = sqlcipher3.connect(db_path)
        # PRAGMA key MUST be set before any other operation. We use
        # the quoted-string form to avoid passing the key through
        # parameter substitution (which sqlite3 would treat as a
        # value rather than as a pragma argument).
        safe = passphrase.replace("'", "''")
        conn.execute(f"PRAGMA key='{safe}'")
        # Touch the schema to force-validate the key. If the key is
        # wrong, this raises DatabaseError immediately rather than
        # silently giving us a broken connection.
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn

    return _connect


# ── Migration: plain → encrypted ─────────────────────────────────


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of an encrypt/decrypt migration."""

    ok: bool
    src_path: Path
    dst_path: Path
    sidelined_path: Path | None
    table_count: int
    error: str | None = None


def encrypt_db(db_path: Path, passphrase: str) -> MigrationResult:
    """Convert a plain SQLite file to a SQLCipher-encrypted one
    in place.

    The original is renamed to ``<name>.pre-encrypt-<ts>.db`` next
    to it. The new encrypted file takes the original's name.

    Idempotent: if the file is already encrypted under this
    passphrase, returns a success result with ``sidelined_path``
    set to None (no migration was needed).

    Args:
        db_path: live DB file path.
        passphrase: the passphrase to encrypt under.

    Returns:
        MigrationResult describing what happened.
    """
    from datetime import datetime

    if not db_path.exists():
        return MigrationResult(
            ok=False,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=None,
            table_count=0,
            error=f"DB file does not exist: {db_path}",
        )

    if is_encrypted_db(db_path):
        # Already encrypted. Confirm the passphrase works.
        try:
            import sqlcipher3

            conn = sqlcipher3.connect(str(db_path))
            safe = passphrase.replace("'", "''")
            conn.execute(f"PRAGMA key='{safe}'")
            n = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            conn.close()
            return MigrationResult(
                ok=True,
                src_path=db_path,
                dst_path=db_path,
                sidelined_path=None,
                table_count=n,
                error="already encrypted with this passphrase (no-op)",
            )
        except Exception as e:
            return MigrationResult(
                ok=False,
                src_path=db_path,
                dst_path=db_path,
                sidelined_path=None,
                table_count=0,
                error=(
                    f"DB is already encrypted but the configured passphrase doesn't open it: {e}"
                ),
            )

    if not is_sqlcipher_available():
        return MigrationResult(
            ok=False,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=None,
            table_count=0,
            error=("sqlcipher3 is not installed. Run 'pip install sqlcipher3-wheels' first."),
        )

    import sqlcipher3

    # Write the encrypted output to a sibling tmp file. We swap
    # only at the very end, when we know the new file is valid.
    tmp_encrypted = db_path.with_suffix(".db.encrypting")
    if tmp_encrypted.exists():
        tmp_encrypted.unlink()

    try:
        # Open the plain DB via sqlcipher3 (it can read plain DBs
        # too, since SQLCipher is a superset of SQLite), ATTACH a
        # new encrypted DB, then SELECT sqlcipher_export() to copy
        # everything across in one atomic SQLCipher operation.
        conn = sqlcipher3.connect(str(db_path))
        try:
            safe = passphrase.replace("'", "''")
            conn.execute(f"ATTACH DATABASE '{tmp_encrypted}' AS encrypted KEY '{safe}'")
            conn.execute("SELECT sqlcipher_export('encrypted')")
            conn.execute("DETACH DATABASE encrypted")
        finally:
            conn.close()

        # Verify: open the new file with sqlcipher3 + same key,
        # count tables.
        conn = sqlcipher3.connect(str(tmp_encrypted))
        try:
            safe = passphrase.replace("'", "''")
            conn.execute(f"PRAGMA key='{safe}'")
            n_tables = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            conn.close()

        if n_tables == 0:
            tmp_encrypted.unlink(missing_ok=True)
            return MigrationResult(
                ok=False,
                src_path=db_path,
                dst_path=db_path,
                sidelined_path=None,
                table_count=0,
                error="encryption produced an empty DB (no tables found)",
            )

        # Confirm the verification ALSO shows the new file is
        # actually encrypted (defensive, in case sqlcipher_export
        # somehow wrote a plain file).
        if not is_encrypted_db(tmp_encrypted):
            tmp_encrypted.unlink(missing_ok=True)
            return MigrationResult(
                ok=False,
                src_path=db_path,
                dst_path=db_path,
                sidelined_path=None,
                table_count=0,
                error="encryption output looks unencrypted; aborting swap",
            )

        # Swap: sideline original, install new.
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        sidelined = db_path.with_name(f"{db_path.stem}.pre-encrypt-{ts}.db")
        db_path.rename(sidelined)
        tmp_encrypted.rename(db_path)

        logger.warning(
            "DB encrypted in place: %s → %s (original sidelined to %s, %d tables)",
            db_path,
            db_path,
            sidelined.name,
            n_tables,
        )

        return MigrationResult(
            ok=True,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=sidelined,
            table_count=n_tables,
        )

    except Exception as e:
        tmp_encrypted.unlink(missing_ok=True)
        return MigrationResult(
            ok=False,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=None,
            table_count=0,
            error=f"encryption failed: {e}",
        )


def decrypt_db(db_path: Path, passphrase: str) -> MigrationResult:
    """Convert a SQLCipher-encrypted file to a plain SQLite one.

    Inverse of ``encrypt_db``. The original is renamed to
    ``<name>.pre-decrypt-<ts>.db``.

    Args:
        db_path: encrypted live DB path.
        passphrase: passphrase that opens the encrypted file.

    Returns:
        MigrationResult.
    """
    from datetime import datetime

    if not db_path.exists():
        return MigrationResult(
            ok=False,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=None,
            table_count=0,
            error=f"DB file does not exist: {db_path}",
        )

    if not is_encrypted_db(db_path):
        return MigrationResult(
            ok=True,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=None,
            table_count=0,
            error="DB is already plain (no-op)",
        )

    if not is_sqlcipher_available():
        return MigrationResult(
            ok=False,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=None,
            table_count=0,
            error="sqlcipher3 is not installed",
        )

    import sqlcipher3

    tmp_plain = db_path.with_suffix(".db.decrypting")
    if tmp_plain.exists():
        tmp_plain.unlink()

    try:
        conn = sqlcipher3.connect(str(db_path))
        try:
            safe = passphrase.replace("'", "''")
            conn.execute(f"PRAGMA key='{safe}'")
            # Attach with KEY='' (empty string) means "no encryption"
            # for the target — the standard SQLCipher idiom for
            # exporting to plain.
            conn.execute(f"ATTACH DATABASE '{tmp_plain}' AS plain KEY ''")
            conn.execute("SELECT sqlcipher_export('plain')")
            conn.execute("DETACH DATABASE plain")
        finally:
            conn.close()

        # Verify
        c2 = sqlite3.connect(str(tmp_plain))
        try:
            n_tables = c2.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            c2.close()

        if n_tables == 0:
            tmp_plain.unlink(missing_ok=True)
            return MigrationResult(
                ok=False,
                src_path=db_path,
                dst_path=db_path,
                sidelined_path=None,
                table_count=0,
                error="decryption produced an empty DB",
            )

        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        sidelined = db_path.with_name(f"{db_path.stem}.pre-decrypt-{ts}.db")
        db_path.rename(sidelined)
        tmp_plain.rename(db_path)
        logger.warning(
            "DB decrypted in place: %s (original sidelined to %s, %d tables)",
            db_path,
            sidelined.name,
            n_tables,
        )

        return MigrationResult(
            ok=True,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=sidelined,
            table_count=n_tables,
        )
    except Exception as e:
        tmp_plain.unlink(missing_ok=True)
        return MigrationResult(
            ok=False,
            src_path=db_path,
            dst_path=db_path,
            sidelined_path=None,
            table_count=0,
            error=f"decryption failed: {e}",
        )
