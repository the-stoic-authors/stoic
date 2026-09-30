# Installing Stoic with Docker

This is the recommended way to run Stoic on a dedicated lab server.
The Docker image bundles Stoic, gunicorn, Caddy (as reverse proxy
with automatic HTTPS), and all system dependencies — there's no
Python virtualenv to maintain, no separate web server to configure,
and updates are one command.

Tested deployments:

  - Linux x86_64 (Ubuntu 22.04+, Debian 12+)
  - macOS (Intel + Apple Silicon) via Docker Desktop
  - Windows 11 via Docker Desktop + WSL2
  - Raspberry Pi 3B and later, Pi OS Lite 64-bit. The 64-bit image
    is required (RDKit ships aarch64 wheels only). **No arm64 image
    is published yet**, so on a Pi you build locally — see
    [Upgrading](#upgrading). A 3B with 1 GB of RAM runs two workers
    with room to spare; see the Administrator manual for the
    `gpu_mem` and cgroup settings worth applying first.

## Prerequisites

A machine with:

  - Docker Engine 24+ and Docker Compose v2
  - 2 GB of free disk space for the image and growing data
  - Network access to GitHub (for pulling the image) and to
    Let's Encrypt (only if exposing publicly)

To install Docker on Ubuntu/Debian:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for the group change to take effect
```

## Quick start

```bash
# 1. Get the deployment manifests
mkdir stoic && cd stoic
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/Caddyfile -o Caddyfile
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/.env.example -o .env

# 2. Edit .env — at minimum set SECRET_KEY and STOIC_DOMAIN
nano .env

# 3. Start
docker compose up -d

# 4. Create the database and the admin account
docker compose exec stoic flask --app stoic_eln init-db --admin-password 'choose-a-real-password'

# 5. Wait ~15 seconds for first-boot, then open your browser
#    For STOIC_DOMAIN=stoic.local → https://stoic.local
#    For STOIC_DOMAIN=lab.example.com → https://lab.example.com
```

**Step 4 is not optional.** Nothing creates the admin user for you:
skip it and the login page appears but no password works. If you
omit `--admin-password` the account is created with `admin123` —
change it immediately or, better, pass your own.

`--app stoic_eln` is required because `FLASK_APP` is deliberately
unset inside the container. Add `--no-seed` if you do not want the
example substances and reaction templates.

The first request triggers Caddy to issue a TLS certificate:

  - **Real domain** → Let's Encrypt cert, ready in ~10 s. Subsequent
    requests serve from cache.
  - **`*.local` domain** → Caddy generates a self-signed cert via
    its internal CA. Browser will warn ("Not Secure" or similar);
    see the "Trusting Caddy's local CA" section below.

## Configuration

Everything lives in `.env`. The two required settings:

### `SECRET_KEY`

A long random string used to sign session cookies. Generate with:

```bash
openssl rand -hex 32
```

Never share this and never commit it. Changing it logs out every
existing user.

### `STOIC_DOMAIN`

Determines the URL Stoic serves on and the TLS strategy:

| Value | TLS | When to use |
|-------|-----|-------------|
| `stoic.local` (default) | Caddy self-signed | LAN-only install, accessible on the local network |
| `lab.example.com` | Let's Encrypt | Public deployment with a real domain |
| `localhost` | HTTP only | Development / testing |

For `*.local` domains to resolve on client devices, you need
either:

  - **mDNS / Bonjour**: works automatically on macOS, iOS, and on
    Linux with `avahi-daemon` installed
  - **`/etc/hosts` entry** on each client machine:
    ```
    192.168.1.42 stoic.local
    ```
  - **A local DNS server** (Pi-hole, your router) pointing
    `stoic.local` at the server's LAN IP

### Optional settings

| Variable | Default | Notes |
|----------|---------|-------|
| `STOIC_TLS_EMAIL` | (blank) | Used for Let's Encrypt renewal notices |
| `STOIC_WORKERS` | `2` | Gunicorn workers. `2` is fine even on a Raspberry Pi 3B (measured: ~230 MiB resident, 460 MB still free) |
| `STOIC_TIMEOUT` | `120` | Per-request timeout in seconds |
| `STOIC_IMAGE` | `ghcr.io/the-stoic-authors/stoic:latest` | Pin a specific version, or name a locally built image |
| `STOIC_INSTANCE_PATH` | `/app/instance` (set in the manifest) | Where `backups/`, `backup.key` and `auth_source` live. Must be inside a volume — see [Backups](#backups) |
| `LAB_NAME` | `Mio Laboratorio` | Default name shown until onboarding wizard runs |
| `DEFAULT_LOCALE` | `it` | UI default language (`it` or `en`) |
| `STOIC_BACKUP_PASSPHRASE` | (blank) | Enables encrypted nightly backups |

## Trusting Caddy's local CA

If you used a `*.local` domain, the first time you open Stoic
the browser shows a warning. Two ways to remove it:

### Option A: install Caddy's root CA on each client

This is the cleanest, "no warning ever again" approach.

```bash
# On the server, find the root CA
docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt

# Copy the certificate to your client (Mac, iOS, Linux, Windows)
# and install/trust it system-wide. macOS:
#   security add-trusted-cert -d -r trustRoot \
#     -k /Library/Keychains/System.keychain root.crt
```

Each client only needs this once.

### iOS / iPadOS (required for PWA install at the bench)

iOS is stricter than desktop browsers: to install Stoic as a PWA
("Add to Home Screen") with a self-signed certificate, you must
install AND trust Caddy's root CA on the device:

1. Get the root CA from the server:
   ```bash
   docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt > caddy-root.crt
   ```
2. Transfer `caddy-root.crt` to the iPad (AirDrop is easiest, or
   email it to yourself).
3. Open the file on the iPad → iOS asks to install a
   configuration profile → Settings → General → VPN & Device
   Management → install the profile.
4. **Crucial extra step**: Settings → General → About →
   Certificate Trust Settings → enable full trust for the Caddy
   root certificate.
5. Reload Stoic in Safari — the padlock is now clean and "Add to
   Home Screen" produces a fully working PWA.

If you skip step 4, Safari keeps warning and the PWA install will
not behave correctly.

### Option B: accept the warning per browser

For one-off access, click "Advanced" → "Proceed to stoic.local"
in the browser warning page. Modern browsers remember the choice
per profile.

## Upgrading

```bash
# Pull the new image version
docker compose pull

# Restart with the new image (state in volumes is preserved)
docker compose up -d
```

**On arm64 (Raspberry Pi and friends), do not run `docker compose
pull`.** The published image is built for `linux/amd64` only, so a
pull replaces a working local build with one the machine cannot
execute, and the container dies with `exec format error`. Build
locally instead — `compose.override.yml` in the repository turns
`image:` into `build: .` — and update with:

```bash
git pull && docker compose build && docker compose up -d
```

Setting `STOIC_IMAGE` to a name that does not exist on the registry
(for example `stoic-local:arm64`) turns an absent-minded `pull`
into a harmless failure rather than a broken container.

To pin a specific version (recommended in production):

```bash
# In .env
STOIC_IMAGE=ghcr.io/the-stoic-authors/stoic:v1.0.0
```

Then `docker compose up -d`.

## Backups

The Stoic container runs a nightly backup automatically at 03:00 UTC
inside the master process. Files land in `backups/` under the
instance directory — `/app/instance/backups`, on the
`stoic-instance` volume alongside the database:

```bash
docker compose exec stoic flask --app stoic_eln backups-list
docker compose cp stoic:/app/instance/backups/<filename> ./
```

Backups are gzipped SQLite files. They are *also* encrypted only if
you set `STOIC_BACKUP_PASSPHRASE` in `.env` (or place a passphrase
in `instance/backup.key`) — treat that secret like a password
manager seed, because losing it makes existing backups unreadable.

Note that a backup contains the **database only**. Attachments live
in a separate volume and are not included; back up
`stoic-attachments` separately if your lab stores files on runs.

### Upgrading from a version before 1.5.6

Earlier versions wrote the instance directory to whatever path Flask
computed from the package location. Inside the image that resolved
to `/opt/venv/var/stoic_eln-instance` — the container's **writable
layer**, not a volume — so `docker compose up -d` destroyed every
nightly backup, along with `backup.key` if backup encryption was on.
The `stoic-backups` volume the manifest mounted was never written to.

From 1.5.6 the path is pinned by `STOIC_INSTANCE_PATH` (set to
`/app/instance` in `docker-compose.yml`), and on first boot Stoic
copies any files still sitting at the old path into the new one,
logging what it moved. The originals are left where they are.

**Before upgrading, rescue what is in the old location**, because
the upgrade recreates the container and that directory goes with it:

```bash
docker compose cp stoic:/opt/venv/var/stoic_eln-instance/backups ./backups-rescued
ls -la ./backups-rescued
```

Then upgrade, and copy them back in if the new instance directory
is empty:

```bash
docker compose cp ./backups-rescued/. stoic:/app/instance/backups/
```

## Stopping and removing

```bash
# Stop the containers, keep volumes
docker compose down

# Stop AND delete all data (DESTRUCTIVE)
docker compose down -v
```

## Troubleshooting

### `docker compose up` returns "address already in use"

Something else on the host (skype, another web server) is on port 80
or 443. Either stop the other service or change the published ports
in `docker-compose.yml`:

```yaml
caddy:
  ports:
    - "8443:443"
```

### Browser shows "ERR_CERT_AUTHORITY_INVALID"

Expected on first visit if `STOIC_DOMAIN=stoic.local`. Either
trust Caddy's root CA (above) or accept the warning per browser.

### Login page never loads, container keeps restarting

```bash
docker compose logs stoic
```

Most common cause: missing `SECRET_KEY` in `.env`.

### Can't reach `stoic.local` from another device

mDNS isn't working on that device. Either install Bonjour /
avahi-daemon, or add a hosts file entry pointing to the server's
LAN IP.
