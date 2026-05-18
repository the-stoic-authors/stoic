#!/usr/bin/env bash
#
# install-macos.sh — Stoic ELN one-shot installer for macOS.
#
# Run with:
#   curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-macos.sh | bash
#
# Or download then run:
#   curl -fsSL -o install-stoic.sh https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-macos.sh
#   bash install-stoic.sh
#
# What it does, in order:
#   1. Verify we're on macOS.
#   2. Check / install Homebrew (the universal mac package manager).
#   3. Install system libraries needed for Stoic's native deps:
#      python@3.12, cairo, pkg-config, freetype, libpng.
#   4. Clone the Stoic repo into ~/Projects/stoic-eln (or update
#      it if already present).
#   5. Create a Python virtualenv and run `pip install -e .`.
#   6. Initialise the database and prompt for the first admin user.
#   7. Print next steps: how to launch in foreground (for trying it
#      out) and how to register as a launchd daemon (for keeping it
#      running across reboots).
#
# Idempotent: re-running the script does the right thing (skips
# what's already done, updates what's out of date). Safe to retry
# after a network hiccup.
#
# Doesn't:
#   - Touch the system Python.
#   - Modify /etc/hosts or firewall rules.
#   - Disable AirPlay Receiver (Stoic defaults to port 5001 to
#     avoid the macOS port-5000 conflict).
#   - Run anything as root. Homebrew prompts for sudo only for
#     its own initial install on a fresh system.
#
# License: AGPLv3 (see the cloned repo's LICENSE file).

set -euo pipefail

# ─── Output helpers (mirror what the `stoic` CLI uses) ───────────

if [ -t 1 ] && [ -z "${STOIC_NO_COLOR:-}" ]; then
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    DIM='\033[2m'
    RESET='\033[0m'
else
    GREEN='' BLUE='' YELLOW='' RED='' BOLD='' DIM='' RESET=''
fi

ok()      { printf "${GREEN}✓${RESET} %s\n" "$*"; }
info()    { printf "${BLUE}→${RESET} %s\n" "$*"; }
warn()    { printf "${YELLOW}⚠${RESET} %s\n" "$*"; }
err()     { printf "${RED}✗${RESET} %s\n" "$*" >&2; }
die()     { err "$*"; exit 1; }
header()  { printf "\n${BOLD}━━ %s ━━${RESET}\n" "$*"; }

# ─── Configuration (override via env vars) ───────────────────────

STOIC_REPO="${STOIC_REPO:-https://github.com/the-stoic-authors/stoic.git}"
STOIC_DIR="${STOIC_DIR:-$HOME/Projects/stoic-eln}"
STOIC_BRANCH="${STOIC_BRANCH:-main}"
STOIC_PORT="${STOIC_PORT:-5001}"

# ─── Step 1: Verify macOS ─────────────────────────────────────────

header "Stoic ELN — macOS installer"

if [ "$(uname -s)" != "Darwin" ]; then
    die "This installer is for macOS only. For Linux, use install-linux.sh."
fi

MACOS_VERSION=$(sw_vers -productVersion)
ok "Running on macOS ${MACOS_VERSION}"

# Apple Silicon vs Intel — pip/brew install slightly different paths
# but both are supported.
ARCH=$(uname -m)
info "Architecture: ${ARCH}"

# ─── Step 2: Homebrew ────────────────────────────────────────────

header "Checking Homebrew"

if command -v brew >/dev/null 2>&1; then
    ok "Homebrew already installed at $(command -v brew)"
else
    info "Homebrew not found — installing it now."
    info "You may be prompted for your password (sudo) once."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for this session (zsh / bash on apple silicon
    # uses /opt/homebrew, Intel uses /usr/local).
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    ok "Homebrew installed."
fi

# ─── Step 3: System libraries ────────────────────────────────────

header "Installing system libraries"

# python@3.12 is preferred over plain python because Stoic targets
# 3.12 specifically. cairo + pkg-config are needed for pycairo,
# which reportlab pulls in transitively via rlPyCairo (for SVG
# rendering of GHS pictograms). freetype + libpng are needed by
# Pillow when building from source on older macOS releases; with
# wheels available they're a no-op.

BREW_PACKAGES="python@3.12 cairo pkg-config freetype libpng"
for pkg in $BREW_PACKAGES; do
    if brew list "$pkg" >/dev/null 2>&1; then
        ok "$pkg already installed"
    else
        info "Installing $pkg..."
        brew install "$pkg"
        ok "$pkg installed"
    fi
done

# Python from Homebrew lives in different paths on Apple Silicon
# vs Intel. Find whichever python3.12 brew put on disk.
PY_BIN=""
for candidate in \
    /opt/homebrew/opt/python@3.12/bin/python3.12 \
    /usr/local/opt/python@3.12/bin/python3.12 \
    $(brew --prefix python@3.12 2>/dev/null)/bin/python3.12 \
    /opt/homebrew/bin/python3.12 \
    /usr/local/bin/python3.12; do
    if [ -x "$candidate" ]; then
        PY_BIN="$candidate"
        break
    fi
done
[ -n "$PY_BIN" ] || die "Couldn't find python3.12 even after brew install. Open an issue."
ok "Using Python: $PY_BIN ($($PY_BIN --version))"

# ─── Step 4: Clone or update repo ────────────────────────────────

header "Fetching Stoic"

if [ -d "$STOIC_DIR/.git" ]; then
    info "Existing checkout at $STOIC_DIR — pulling latest"
    git -C "$STOIC_DIR" fetch origin "$STOIC_BRANCH"
    # Only ff-merge if there are no local changes, otherwise stash
    # warning and skip — we don't want to clobber the user's WIP.
    if git -C "$STOIC_DIR" diff --quiet && git -C "$STOIC_DIR" diff --cached --quiet; then
        git -C "$STOIC_DIR" merge --ff-only "origin/$STOIC_BRANCH" || \
            warn "Couldn't fast-forward — your local branch has diverged. Skipping pull."
    else
        warn "Local changes present — leaving working tree alone."
    fi
    ok "Repo updated"
else
    info "Cloning $STOIC_REPO into $STOIC_DIR"
    mkdir -p "$(dirname "$STOIC_DIR")"
    git clone --branch "$STOIC_BRANCH" "$STOIC_REPO" "$STOIC_DIR"
    ok "Repo cloned"
fi

cd "$STOIC_DIR"

# ─── Step 5: Virtualenv + Stoic + deps ───────────────────────────

header "Installing Stoic"

if [ -d "$STOIC_DIR/.venv" ]; then
    ok ".venv exists"
else
    info "Creating .venv with $PY_BIN"
    "$PY_BIN" -m venv "$STOIC_DIR/.venv"
    ok ".venv created"
fi

info "Upgrading pip in venv"
"$STOIC_DIR/.venv/bin/pip" install --upgrade pip --quiet

info "Installing Stoic and dependencies (this takes 1–2 minutes the first time)"
"$STOIC_DIR/.venv/bin/pip" install -e "$STOIC_DIR" --quiet

ok "Stoic installed in editable mode"

# Sanity-check that the entry point landed.
if "$STOIC_DIR/.venv/bin/stoic" --version >/dev/null 2>&1; then
    STOIC_VER=$("$STOIC_DIR/.venv/bin/stoic" --version | awk '{print $NF}')
    ok "stoic CLI working: version $STOIC_VER"
else
    warn "stoic CLI didn't return a version — check the install log above."
fi

# ─── Step 6: Initialise DB + create admin ────────────────────────

header "Setting up the database"

# stoic install does init-db + (optionally) create-user. Pass the
# port through env so the launchd plist (if registered later) uses
# the right one.
export FLASK_APP=stoic_eln

# Run init-db. Idempotent: if the DB already has the schema, this
# is a no-op.
"$STOIC_DIR/.venv/bin/python" -m flask init-db || die "init-db failed"
ok "Database initialised"

# Check if any users exist. If yes, skip the admin prompt.
USER_COUNT=$("$STOIC_DIR/.venv/bin/python" -c "
from stoic_eln import create_app
from stoic_eln.extensions import db
from stoic_eln.models import User
app = create_app()
with app.app_context():
    print(db.session.query(User).count())
" 2>/dev/null || echo "0")

if [ "$USER_COUNT" -gt 0 ]; then
    ok "$USER_COUNT user(s) already in DB — skipping admin creation"
else
    header "First admin user"
    info "We'll prompt for the first admin's username, email, and password."
    info "Username can be anything you like (often your first name)."
    "$STOIC_DIR/.venv/bin/python" -m flask create-user --admin || \
        warn "Admin creation skipped or failed. You can rerun later with:"
    warn "  cd $STOIC_DIR && .venv/bin/python -m flask create-user --admin"
fi

# ─── Step 7: Next steps ──────────────────────────────────────────

header "Done"

cat <<EOF

${BOLD}Stoic is installed.${RESET}

To try it out (foreground, Ctrl+C to stop):

    cd $STOIC_DIR
    .venv/bin/stoic start --foreground --port $STOIC_PORT

Then open http://127.0.0.1:$STOIC_PORT in your browser.

To run it as a background daemon (launchd; starts at login,
auto-restarts on crash):

    cd $STOIC_DIR
    .venv/bin/stoic install --daemon --port $STOIC_PORT

${DIM}Notes:${RESET}
  - Stoic uses port $STOIC_PORT by default to avoid conflict
    with macOS AirPlay Receiver (which uses port 5000).
  - To check status anytime:  .venv/bin/stoic status
  - To stop the daemon:       .venv/bin/stoic stop
  - To update Stoic later:    .venv/bin/stoic update

${DIM}Add to your shell PATH (optional):${RESET}
  echo 'export PATH="$STOIC_DIR/.venv/bin:\$PATH"' >> ~/.zshrc

Documentation: https://github.com/the-stoic-authors/stoic
Issues:        https://github.com/the-stoic-authors/stoic/issues

EOF
