# Stoic ELN — Administrator manual

This manual covers installation, configuration, user management,
data security, backup, audit, and deployment of Stoic. Intended
for those with system responsibility. For lab workflow see the
user manual; for code modifications see the developer manual.

---

## Installation

### Requirements

- Python 3.12 or later
- ~500 MB disk for the software + ~10–50 MB for the initial DB
- Mac, Linux x86_64, or Raspberry Pi (4 or 5 recommended)

### Development environment setup (Mac/Linux)

```bash
# Clone or extract the source to ~/Projects/stoic-eln
cd ~/Projects/stoic-eln

# Create the virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install Stoic + dependencies
pip install -e .
```

Main dependencies installed automatically:

- **Flask 3.x** + Flask-Babel + Flask-Login + Flask-WTF
- **SQLAlchemy 2.x** + sqlcipher3-wheels (for live DB encryption)
- **RDKit** (molecule rendering)
- **ReportLab** + svglib (PDF generation: labels, sheets, audit
  log)
- **cryptography** (backup encryption AES-256-GCM, Argon2id KDF)
- **APScheduler** (nightly backups)
- **PIL/Pillow** (image manipulation)

### Initial configuration

Open `~/.zshrc` (or `~/.bashrc`) and add:

```bash
export FLASK_APP=stoic_eln
```

Then initialise the database and create the first administrator:

```bash
flask init-db
flask create-user --admin
# Username: rico
# Full name: Rico Di Rosso
# Operator code: RDR
# Password: [strong choice]
```

Start in development mode:

```bash
flask run
```

Open `http://localhost:5000` in the browser and login with the
just-created account.

---

## User management

### Roles

Stoic has three roles, ordered by increasing privileges:

| Role | What they can do |
|---|---|
| **User** | Runs experiments, consumes batches, uploads attachments. Doesn't modify reaction templates or catalog substances. |
| **Supervisor** | All of user, plus: creates/edits reactions and substances, manages mixtures and suppliers. |
| **Administrator** | All of supervisor, plus: manages users, global configuration, backups, full audit log. |

### Create a user

From CLI:

```bash
flask create-user
# Username: alice
# Full name: Alice Rossi
# Operator code: ALR
# Role: user / supervisor / admin
# Password: [...]
```

From UI: **Settings → Users → New user**. Fill the fields and
save. Stoic has no self-signup: users are always created by an
admin. Share username and password with the new user, who will
change the password on first login from Profile → Change
password.

### Edit a user

**Settings → Users → [name]**. You can modify full name,
operator code, role, default locale (it/en), active/inactive
status. You cannot modify your own role (for safety: needs a
second admin to perform a downgrade).

### Reset password

**Settings → Users → [name] → Reset password**. Generates a new
temporary password, communicate it to the user. Forces them to
change it on next login.

### Deactivate a user

Same page, "Active" toggle. Deactivate instead of delete:
inactive users can't log in but remain in historical records
(runs executed, attachments uploaded). Deleting a user breaks
references.

---

## Encryption and backups

Stoic offers three protection layers:

1. **Automatic backups** — not encrypted by default. Live in
   `instance/backups/`.
2. **Backup encryption** (AES-256-GCM, Argon2id KDF) — when you
   enable a passphrase. Future backups saved as `.db.gz.enc`.
3. **Live DB encryption** (SQLCipher 4, AES-256-CBC + HMAC-
   SHA512 at the page level) — `stoic_eln.db` opaque without
   passphrase.

The three layers are independent: you can have only plain
backups (default), encrypted backups but plain live DB, or both
encrypted. **The passphrase is the same for both** — only one
secret to remember.

### Passphrase sources

From `Settings → Encryption & backups → Passphrase source`:

| Mode | Where the passphrase lives | TTY at boot? | Threat model |
|---|---|---|---|
| `none` | nowhere | no | No encryption. Default fresh install. |
| `prompt` | RAM only | **yes** | Stolen disk = protected. Max security. |
| `file` | `instance/backup.key` (0600) | no | Convenient for development. |
| `env` | `STOIC_BACKUP_PASSPHRASE` | no | Server with systemd-creds or Docker secrets. |

**Which to choose:**

- **Personal Mac dev, FileVault active**: `file` or `prompt`.
  FileVault already protects the disk when off.
- **Mac/desktop without disk encryption**: `prompt`. The
  passphrase doesn't exist on disk; whoever stole the filesystem
  finds only encrypted data without key.
- **Linux server with auto-restart**: `env` (via systemd
  EnvironmentFile or systemd-creds + TPM).
- **Small Raspberry Pi**: `prompt` with tmux for persistent
  sessions, or `file` if the Pi is in a physically secure place.

### Enabling live DB encryption

1. Configure a passphrase: pick a mode (e.g. `prompt`), save
2. Enter the passphrase
3. Stop Stoic (`Ctrl-C` on `flask run`)
4. Run: `flask db-encrypt --yes` — first makes a safety backup,
   then encrypts in place
5. Restart Stoic

From here, the `stoic_eln.db` file is opaque. Opened with any
SQLite client shows "file is not a database". Only Stoic with
the correct passphrase can read it.

### Decrypting the live DB (rollback)

```bash
flask db-decrypt --yes
```

Stop Stoic first. Creates a pre-decrypt backup, then overwrites
with the plain version. Restart Stoic normally.

### Status

```bash
flask db-status
# Output: "Live DB at instance/stoic_eln.db: encrypted (SQLCipher)"
# Or: "Live DB at instance/stoic_eln.db: plain SQLite"
```

### Manual backup

```bash
flask backup
# Creates: instance/backups/stoic_eln-20260513-093000.db.gz[.enc]
```

In `prompt` mode you're asked for the passphrase. In `file` or
`env` mode it's automatic.

### Automatic scheduler configuration

`Settings → Encryption & backups → Automatic backups`:

- **Hour (UTC)**: default 03:00
- **Minute**: default 0
- **Keep last (days)**: default 30 (rolling daily backups)
- **+ one per week for (weeks)**: default 12 (rolling weekly
  backups after the dailies)

Stoic automatically maintains the configured retention. Older
backups are deleted every night. Encryption (if active) is
applied to all automatic backups.

### Restore

`Settings → Encryption & backups → Existing backups → Restore`.

Stoic:
1. Creates a safety backup of the current DB (`pre-restore`)
2. Replaces the DB with the backup content
3. Restart required

If the backup was encrypted and the current system is encrypted,
the restore automatically re-encrypts with the current passphrase.

### Changing the passphrase

Important: **changing the passphrase makes all existing
encrypted backups unreadable**. Do this only if you're sure or
have accepted the loss.

1. Make a safety backup with the current passphrase
2. `Settings → Encryption & backups → Change passphrase`
3. Decrypt the live DB (if encrypted) before changing
4. Change, re-encrypt

The script `flask db-decrypt && [change passphrase] && flask
db-encrypt` is the safe workflow.

### What to do if you lose the passphrase

Symptoms: Stoic won't start ("Cannot decrypt"), or encrypted
backups don't open.

- If the live DB is still plain: only encrypted backups are
  lost. The system continues to work normally. Consider
  temporarily disabling encryption (`Settings → ...` → pick
  `none`).
- If the live DB is encrypted and the passphrase is lost: data
  is unrecoverable. You have to start from scratch. Hard lesson:
  always test the passphrase before encrypting the live DB.

---

## Global configuration

`Settings → General settings`.

### Currency

ISO 4217 3-letter code (EUR, USD, JPY, etc.). Stoic shows the
recognised symbol (€, $, £, ¥) or the code. Used for all costs
(batches, orders, runs, statistics).

### Run code template

Format generated for the batch codes of run products. Default:
`{reaction.code}-{year}-{seq:03d}` → `EST-MEOH-2026-001`.
Customisable from `Settings → Run code`.

### Preparation code template

Same for mixture preparations. Default:
`{mixture.slug}-{year}-{seq:03d}` → `HCL1N-2026-001`.

### Default language

Default for new users. Each user can change their own from
profile.

### Global thresholds

- **Default minimum threshold**: when you create a new substance
  without specifying, this is the threshold below which it will
  appear in dashboard alerts.

---

## Audit log

`Settings → Audit log`. All significant actions are recorded
with:

- UTC timestamp
- User
- Action (`create`, `update`, `delete`, `login`, `logout`,
  `download_run_pdf`, `upload_attachment`, etc.)
- Entity (type + ID)
- Details (JSON with relevant fields)

Available filters: by user, by action, by entity, by date range.
Exportable as **CSV** or **PDF**.

The audit log is append-only: no route modifies it. Only admins
see the full log. Users see their own records from `Profile`.

---

## Deployment

### Local development (Mac)

Described above. `flask run` on localhost:5000.

### Production on Linux + systemd

Create `/etc/systemd/system/stoic.service`:

```ini
[Unit]
Description=Stoic ELN
After=network.target

[Service]
Type=simple
User=stoic
WorkingDirectory=/opt/stoic-eln
EnvironmentFile=/etc/stoic/secret.env
ExecStart=/opt/stoic-eln/.venv/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --timeout 120 \
    "stoic_eln:create_app()"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The file `/etc/stoic/secret.env`:

```
STOIC_BACKUP_PASSPHRASE=your-secret-passphrase
```

Permissions: `chmod 600 /etc/stoic/secret.env`, `chown root:stoic
/etc/stoic/secret.env` (readable only by root and the stoic
group). Or use `systemd-creds` + TPM for at-rest encryption of
the secret.

Enable and start:

```bash
systemctl enable stoic
systemctl start stoic
systemctl status stoic
```

### Production on Raspberry Pi

Same systemd configuration, but with `--workers 1` (the Pi has
less RAM) and possibly `--bind 127.0.0.1:5000` + nginx reverse
proxy in front if you want HTTPS.

For `prompt` mode on Pi (passphrase never on disk):

```bash
# SSH to the Pi
ssh pi@stoic-server

# Persistent tmux session
tmux new -s stoic
cd /opt/stoic-eln
source .venv/bin/activate
flask run --host 0.0.0.0 --port 5000
# Enter passphrase when asked
# Ctrl-B D to detach (session stays in background)
# tmux attach -t stoic to re-attach
```

Drawback: if the Pi restarts (kernel update, blackout), you need
manual SSH to re-type the passphrase. Classic security vs
availability tradeoff.

### Network and firewall

Stoic doesn't implement rate limiting or anti-bruteforce
protection beyond login. **Don't expose it directly on the
Internet.** Use it only on the lab's local network, or behind
VPN.

If you need remote access: Tailscale or WireGuard work well.

---

## Troubleshooting

**Stoic won't start: "no such table".** The DB isn't initialised.
`flask init-db`.

**"file is not a database".** The DB is encrypted but no
passphrase. Verify mode (`prompt`/`file`/`env`) and provide the
passphrase. Test: `flask passphrase-test`.

**"Cannot decrypt".** Wrong passphrase, or corrupted DB. Try
`flask db-status`. If passphrase is correct but error, restore
from a recent backup.

**Nightly backups don't run.** Check APScheduler:
`flask scheduler-status`. The scheduler lives inside the Stoic
process; if Stoic is down, no backups. Check the systemd log:
`journalctl -u stoic -f`.

**Attachment not visible after upload.** Check `ATTACHMENTS_DIR`
in `config.py` — must be writeable. Default
`instance/attachments/`.

**Database migration failed.** Stoic has `_ensure_schema` that
creates missing tables at boot (idempotent). Migrations of
existing data (e.g. new columns) are in `scripts/migrate_*.py`,
to be run manually after upgrade: `python scripts/migrate_weekN.py`.

---

## Off-site backups

The local nightly backup protects you from DB corruption but
not from fire or computer theft. Configure periodic sync of the
`instance/backups/` folder to external storage:

- Rclone to S3/Backblaze B2/Google Drive
- Restic with remote repository
- Borg with backup server
- Time Machine (Mac) includes `instance/backups/` automatically
  if the parent folder is included

Encrypted backups are **safe to copy to untrusted cloud** —
whoever takes the file cannot open it without the passphrase.

---

## Updating

```bash
cd ~/Projects/stoic-eln
git pull  # or tar -xzvf new-patch.tar.gz
.venv/bin/pip install -e .  # update if deps changed
```

Schema migrations are automatic (idempotent). If a patch includes
a `scripts/migrate_*.py` script, PATCH-NOTES specifies it and
tells you to run it manually.

After update, restart Stoic. Good practice: make a manual backup
first (`flask backup`).
