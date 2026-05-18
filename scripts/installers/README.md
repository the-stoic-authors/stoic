# Stoic Installers

One-shot installers that take a fresh machine from "nothing" to
"Stoic running and ready to log in".

## macOS

```bash
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-macos.sh | bash
```

Or, if you prefer to read the script first (recommended):

```bash
curl -fsSL -o install-stoic.sh \
    https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-macos.sh
less install-stoic.sh   # review
bash install-stoic.sh   # run
```

Tested on macOS 14 Sonoma and macOS 15 Sequoia, both Intel and
Apple Silicon. Requires admin password once during the Homebrew
install on a fresh system.

What it does:

1. Verifies the system is macOS.
2. Installs Homebrew if missing.
3. Installs system libraries: `python@3.12`, `cairo`,
   `pkg-config`, `freetype`, `libpng`.
4. Clones the repo into `~/Projects/stoic-eln`.
5. Creates a virtualenv and installs Stoic + dependencies in
   editable mode.
6. Initialises the database and prompts for the first admin user.
7. Prints next steps (foreground run vs daemon registration).

Idempotent: safe to re-run. Skips work that's already done.

### Environment variables

Override defaults by setting these before running:

| Var            | Default                                            |
|----------------|----------------------------------------------------|
| `STOIC_REPO`   | `https://github.com/the-stoic-authors/stoic.git`   |
| `STOIC_DIR`    | `$HOME/Projects/stoic-eln`                         |
| `STOIC_BRANCH` | `main`                                             |
| `STOIC_PORT`   | `5001`                                             |

Example for a development branch:

```bash
STOIC_BRANCH=feat/new-thing bash install-stoic.sh
```

### Why port 5001?

macOS has AirPlay Receiver enabled by default since Monterey,
and it listens on TCP port 5000. If Stoic tried to bind 5000 it
would silently lose to AirPlay (responding 403 Forbidden from
`AirTunes`). Default 5001 avoids the conflict.

If you really want 5000, disable AirPlay Receiver in System
Settings → General → AirDrop & Handoff, then pass
`STOIC_PORT=5000`.

## Linux (Debian / Ubuntu / Raspberry Pi)

Coming in patch 15.3.

## Windows

Not supported (deliberate scope choice). Use WSL2 with the Linux
installer when it lands, or run Stoic in a VM.
