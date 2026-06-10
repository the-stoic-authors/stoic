#!/usr/bin/env bash
#
# Stoic ELN — Linux server installer (Docker-based)
#
# From a fresh Ubuntu Server / Debian box to a running Stoic in a
# few minutes:
#
#   curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-linux.sh | bash
#
# or, if you prefer to read before running (good instinct):
#
#   curl -fsSLO https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-linux.sh
#   less install-linux.sh
#   bash install-linux.sh
#
# What it does, in order:
#   1. Installs Docker Engine + Compose plugin if missing (via the
#      official get.docker.com script)
#   2. Creates ~/stoic/ and downloads docker-compose.yml, Caddyfile,
#      .env.example from the main branch
#   3. Generates a random SECRET_KEY and writes .env
#   4. Asks for the domain (default: stoic.local)
#   5. Runs `docker compose up -d`
#   6. Prints where to point your browser
#
# The script is idempotent: re-running it won't clobber an existing
# .env or your data volumes.

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/the-stoic-authors/stoic/main"
INSTALL_DIR="${STOIC_INSTALL_DIR:-$HOME/stoic}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '\033[36m→ %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

bold "Stoic ELN — Linux installer"
echo

# ── 0. Sanity ───────────────────────────────────────────────────

[ "$(id -u)" -eq 0 ] && die "Don't run this as root. Run as a normal user; sudo is used only where needed."

command -v curl >/dev/null 2>&1 || die "curl is required. Install it first: sudo apt-get install -y curl"

# ── 1. Docker ───────────────────────────────────────────────────

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker $(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) with Compose already installed"
else
    info "Installing Docker Engine via get.docker.com…"
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    warn "Your user was added to the 'docker' group."
    warn "You must LOG OUT and BACK IN (or run 'newgrp docker') before docker works without sudo."
    warn "Then re-run this script to continue."
    exit 0
fi

# ── 2. Download manifests ───────────────────────────────────────

info "Setting up $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

for f in docker-compose.yml Caddyfile; do
    if [ -f "$f" ]; then
        ok "$f already present (not overwritten — delete it to re-download)"
    else
        curl -fsSL "$REPO_RAW/$f" -o "$f"
        ok "downloaded $f"
    fi
done

# ── 3. .env ─────────────────────────────────────────────────────

if [ -f .env ]; then
    ok ".env already present — keeping your existing configuration"
else
    curl -fsSL "$REPO_RAW/.env.example" -o .env

    SECRET_KEY=$(head -c 32 /dev/urandom | od -A n -t x1 | tr -d ' \n')
    # Replace the blank SECRET_KEY= line
    sed -i "s/^SECRET_KEY=$/SECRET_KEY=$SECRET_KEY/" .env
    ok "generated SECRET_KEY"

    echo
    bold "Which domain should Stoic serve on?"
    echo "  - stoic.local       LAN-only, self-signed HTTPS (default)"
    echo "  - lab.example.com   your real domain, automatic Let's Encrypt"
    echo "  - localhost         HTTP only, for testing"
    printf "Domain [stoic.local]: "
    # Read from /dev/tty so this works even when the script itself
    # is piped from curl.
    read -r DOMAIN < /dev/tty || DOMAIN=""
    DOMAIN="${DOMAIN:-stoic.local}"
    sed -i "s/^STOIC_DOMAIN=.*/STOIC_DOMAIN=$DOMAIN/" .env
    ok "STOIC_DOMAIN=$DOMAIN"
fi

# ── 4. Start ────────────────────────────────────────────────────

info "Starting Stoic (this pulls/builds the image on first run — a few minutes)…"
docker compose up -d

# ── 5. Done ─────────────────────────────────────────────────────

DOMAIN=$(grep "^STOIC_DOMAIN=" .env | cut -d= -f2)
echo
bold "Stoic is starting."
echo
echo "  Open:        https://$DOMAIN"
if [[ "$DOMAIN" == *.local || "$DOMAIN" == *.lan ]]; then
    echo
    echo "  Note: with a .local domain the browser will warn about the"
    echo "  self-signed certificate on first visit. Accept it, or install"
    echo "  Caddy's root CA on your devices (see docs/en/install-docker.md,"
    echo "  section 'Trusting Caddy's local CA')."
    echo
    echo "  For other devices to resolve $DOMAIN you need mDNS (avahi)"
    echo "  on this server, or a hosts-file/DNS entry pointing at this"
    echo "  machine's LAN IP: $(hostname -I 2>/dev/null | awk '{print $1}')"
fi
echo
echo "  Logs:        cd $INSTALL_DIR && docker compose logs -f"
echo "  Stop:        cd $INSTALL_DIR && docker compose down"
echo "  Update:      cd $INSTALL_DIR && docker compose pull && docker compose up -d"
echo
ok "Installation complete. The first account you create becomes the admin."
