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
  - Raspberry Pi 4 + Pi OS 64-bit (arm64 image — see Patch E)

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

# 4. Wait ~15 seconds for first-boot, then open your browser
#    For STOIC_DOMAIN=stoic.local → https://stoic.local
#    For STOIC_DOMAIN=lab.example.com → https://lab.example.com
```

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
| `STOIC_WORKERS` | `2` | Gunicorn workers. Use `1` on a Pi 3B |
| `STOIC_TIMEOUT` | `120` | Per-request timeout in seconds |
| `STOIC_IMAGE` | `ghcr.io/the-stoic-authors/stoic:latest` | Pin a specific version |
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

To pin a specific version (recommended in production):

```bash
# In .env
STOIC_IMAGE=ghcr.io/the-stoic-authors/stoic:v1.0.0
```

Then `docker compose up -d`.

## Backups

The Stoic container runs a nightly backup automatically at 03:00 UTC
inside the master process. The encrypted file lands in the
`stoic-backups` named volume. To extract a backup to the host:

```bash
docker compose exec stoic ls -la /app/var/backups
docker compose cp stoic:/app/var/backups/<filename> ./
```

To enable encryption, set `STOIC_BACKUP_PASSPHRASE` in `.env`
(treat it like a password manager seed — losing it makes existing
backups unreadable).

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
