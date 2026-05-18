"""Stoic ELN — Encryption for database backups.

Encrypts/decrypts backup blobs using AES-256-GCM (authenticated
encryption) with keys derived from a user-supplied passphrase via
Argon2id.

# Why AES-256-GCM

AES-GCM is the standard for authenticated symmetric encryption in
2026: it provides both confidentiality and authenticity (a tampered
ciphertext fails to decrypt, no padding-oracle pitfalls). 256-bit
keys are the conservative choice for "data at rest for years".

# Why Argon2id for KDF

Argon2id is the modern password-hash function (winner of the
Password Hashing Competition, recommended by RFC 9106). It's
memory-hard, which means GPU/ASIC attacks against a stolen
backup file are dramatically slower than against PBKDF2/bcrypt.
Stoic already depends on argon2-cffi for user passwords, so we
get this for free.

# File format

Each encrypted backup is a single binary file with this layout:

    +------------+------------+-----------+------+------------+
    | magic      | version    | salt      | nonce| ciphertext |
    | 8 bytes    | 1 byte     | 16 bytes  | 12 B | variable   |
    | "STOICENC"  | 0x01       | random    | rand | + 16B tag  |
    +------------+------------+-----------+------+------------+

- **magic** "STOICENC" makes the format sniffable without a
  catalog; lets us detect encrypted-vs-plain backups on read
  without renaming files.
- **version** byte allows future format changes (algorithm
  upgrade, KDF parameter changes) without breaking old backups.
- **salt** is per-file random; derived key changes for every
  backup even if the passphrase is reused.
- **nonce** is per-file random (AES-GCM requires nonces never to
  repeat under the same key; with random 96-bit nonces and ~10⁹
  backups, collision probability is negligible).
- **ciphertext** includes the 16-byte GCM auth tag at the end
  (per python-cryptography convention).

The plaintext we encrypt is the gzipped SQLite dump (so the
encrypted file is roughly the same size as the unencrypted one,
plus ~45 bytes of header).

# Passphrase storage

This module **does not** persist the passphrase. It only accepts
it via the ``passphrase`` parameter. Higher-level code resolves
the passphrase via:

  1. ``STOIC_BACKUP_PASSPHRASE`` environment variable
  2. ``instance/backup.key`` file (one line)
  3. Otherwise, encryption is unavailable

The intent is that an attacker who gets the .db.gz.enc file
without the passphrase has nothing.

# Loss of passphrase = total data loss

By design: if you lose the passphrase, the backup is unrecoverable.
This is the entire point of encryption. Stoic logs a clear warning
when encryption is configured, but cannot help with key recovery.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ── File format constants ────────────────────────────────────────

MAGIC = b"STOICENC"
VERSION = 1
SALT_BYTES = 16
NONCE_BYTES = 12  # AES-GCM standard
KEY_BYTES = 32    # AES-256
HEADER_LEN = len(MAGIC) + 1 + SALT_BYTES + NONCE_BYTES  # 37 bytes

# Argon2id parameters — moderate strength for a backup KDF.
# We're not hashing passwords for login (where memory is a
# concern); we're deriving a key once per backup, so we can
# afford higher cost.
#
# These figures take ~250ms on a 2020-era laptop, ~50ms on
# modern server-class hardware. Backup creation is not
# latency-sensitive, so this is fine.
_KDF_TIME_COST = 3
_KDF_MEMORY_COST = 64 * 1024   # 64 MiB
_KDF_PARALLELISM = 2


# ── Passphrase resolution ────────────────────────────────────────


def resolve_passphrase(instance_path: Path) -> str | None:
    """Find the master passphrase. Delegates to the passphrase
    store, which dispatches on the configured source (prompt /
    file / env).

    Kept as a thin wrapper for backward compatibility with code
    that still imports from this module. New code should use
    ``stoic_eln.services.passphrase_store.get_passphrase``
    directly to make the contract clearer.
    """
    from stoic_eln.services import passphrase_store
    return passphrase_store.get_passphrase(instance_path)


def has_passphrase(instance_path: Path) -> bool:
    """Convenience: True if a passphrase is reachable WITHOUT
    blocking on user input. Delegates to the store's predicate
    version (``has_passphrase_available``). Safe to call from
    web endpoints / templates which mustn't prompt on stdin."""
    from stoic_eln.services import passphrase_store
    return passphrase_store.has_passphrase_available(instance_path)


def write_passphrase_file(instance_path: Path, passphrase: str) -> Path:
    """Write the passphrase to ``instance/backup.key`` with 0600
    perms (Unix). Caller is expected to validate the passphrase
    first by round-tripping a test blob (see ``verify_passphrase``).

    Returns the path written.
    """
    if not passphrase or not passphrase.strip():
        raise ValueError("passphrase cannot be empty")

    instance_path.mkdir(parents=True, exist_ok=True)
    key_file = instance_path / "backup.key"
    # Write atomically: write to tmp + rename, so a crash mid-write
    # can't leave a half-written key file.
    tmp = key_file.with_suffix(".key.tmp")
    tmp.write_text(passphrase.strip(), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Best-effort on platforms without POSIX perms
    tmp.replace(key_file)
    return key_file


# ── Core crypto ──────────────────────────────────────────────────


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte key from passphrase + salt using Argon2id."""
    from argon2.low_level import Type, hash_secret_raw
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=_KDF_TIME_COST,
        memory_cost=_KDF_MEMORY_COST,
        parallelism=_KDF_PARALLELISM,
        hash_len=KEY_BYTES,
        type=Type.ID,
    )


def encrypt_bytes(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt ``plaintext`` and return the full file bytes
    (header + ciphertext + tag).

    Each call generates a fresh random salt and nonce, so two
    encryptions of the same plaintext under the same passphrase
    produce different ciphertexts (probabilistic encryption).
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    key = _derive_key(passphrase, salt)

    aes = AESGCM(key)
    ct = aes.encrypt(nonce, plaintext, associated_data=None)

    out = bytearray()
    out.extend(MAGIC)
    out.append(VERSION)
    out.extend(salt)
    out.extend(nonce)
    out.extend(ct)
    return bytes(out)


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """Decrypt a full encrypted blob and return the plaintext.

    Raises:
        ValueError: if the magic doesn't match or the format
            version is unsupported.
        cryptography.exceptions.InvalidTag: if the passphrase is
            wrong or the ciphertext has been tampered with. (We
            let this bubble up so the caller can show a clear
            "wrong passphrase or corrupted file" error.)
    """
    if not is_encrypted(blob[: len(MAGIC)]):
        raise ValueError("not a Stoic encrypted backup (bad magic)")

    if blob[len(MAGIC)] != VERSION:
        raise ValueError(
            f"unsupported encrypted backup version {blob[len(MAGIC)]!r}; "
            f"this Stoic build supports version {VERSION}"
        )

    salt = blob[len(MAGIC) + 1 : len(MAGIC) + 1 + SALT_BYTES]
    nonce_off = len(MAGIC) + 1 + SALT_BYTES
    nonce = blob[nonce_off : nonce_off + NONCE_BYTES]
    ct = blob[nonce_off + NONCE_BYTES :]

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _derive_key(passphrase, salt)
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, associated_data=None)


def is_encrypted(prefix: bytes) -> bool:
    """Check whether the given byte prefix starts with our magic.

    Designed to be cheap: callers pass the first few bytes of a
    file to decide whether to route through decrypt_bytes() or
    treat it as a plain (legacy) gzipped backup.
    """
    return prefix.startswith(MAGIC)


# ── Passphrase verification ──────────────────────────────────────


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of a self-test encrypt+decrypt round trip."""
    ok: bool
    error: str | None = None


def verify_passphrase(passphrase: str) -> VerificationResult:
    """Encrypt and decrypt a known blob with the given passphrase
    to confirm the crypto stack is functional. Used at setup time
    so the user can't write a passphrase that fails on first real
    backup.
    """
    try:
        probe = b"stoic-verify-" + secrets.token_bytes(16)
        ct = encrypt_bytes(probe, passphrase)
        pt = decrypt_bytes(ct, passphrase)
        if pt != probe:
            return VerificationResult(False, "round-trip produced wrong plaintext")
        return VerificationResult(True)
    except Exception as e:
        return VerificationResult(False, str(e))
