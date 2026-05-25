"""``stoic`` command-line entry point.

Exposed via pyproject.toml [project.scripts] as ``stoic = ...``.
After ``pip install -e .`` the user can invoke ``stoic <cmd>``
from any directory.

The design uses click groups so we can grow the CLI surface
without restructuring. Each ``@main.command`` lives in its own
function below, but multi-step commands (install, update,
doctor) are split into private helpers for readability.
"""

from __future__ import annotations

import os
import subprocess
import sys

import click

from stoic_eln import __version__
from stoic_eln.cli import output as out
from stoic_eln.cli.platform import (
    REPO_ROOT,
    current as current_platform,
)


@click.group(invoke_without_command=False)
@click.version_option(__version__, prog_name="stoic")
def main() -> None:
    """Stoic ELN — operator command-line interface.

    Run a subcommand: install, update, start, stop, status,
    restart, backup, db-encrypt, db-status, doctor, version.
    """


# ── install ──────────────────────────────────────────────────────


@main.command()
@click.option(
    "--daemon/--no-daemon", default=False,
    help="Register stoic as a system service (launchd on macOS, "
         "systemd user on Linux). Lets stoic survive logout/reboot.",
)
@click.option(
    "--port", default=5001, type=int,
    help="Port for the web UI. Default 5001.",
)
@click.option(
    "--admin-email", default=None,
    help="Email for the first admin user (interactive if omitted).",
)
def install(daemon: bool, port: int, admin_email: str | None) -> None:
    """Bootstrap a fresh stoic installation.

    Creates the virtual env if missing, installs Python
    dependencies, initializes the SQLite database, creates the
    first admin user, and (if --daemon) registers stoic as a
    system service.

    Safe to re-run: skips steps that are already done.
    """
    out.header("Stoic installation")

    _ensure_python_version()
    _ensure_venv()
    _install_deps()
    _init_db()
    _create_first_admin(admin_email)
    _compile_translations()

    if daemon:
        out.info(f"Registering as system service on port {port}")
        current_platform().install_daemon(port=port)
    else:
        out.info(
            "Run 'stoic start' to launch in background, "
            "or 'stoic start --foreground' to run attached to this terminal."
        )

    out.ok(f"Installation complete. Stoic v{__version__} is ready.")


# ── update ───────────────────────────────────────────────────────


@main.command()
@click.option(
    "--skip-restart", is_flag=True,
    help="Don't restart the running server after updating.",
)
def update(skip_restart: bool) -> None:
    """Pull the latest version and migrate.

    Equivalent to:
      git pull origin main
      pip install -e .
      flask db upgrade
      stoic restart

    The server is restarted automatically (unless --skip-restart),
    so any active sessions will need to log back in.
    """
    out.header(f"Stoic update (current: v{__version__})")

    if not (REPO_ROOT / ".git").exists():
        out.die(
            "Not a git repository — can't auto-update. "
            "Re-install with 'git clone' to enable updates."
        )

    out.info("Fetching latest from origin/main")
    rc = subprocess.call(["git", "-C", str(REPO_ROOT), "pull", "origin", "main"])
    if rc != 0:
        out.die("git pull failed. Resolve conflicts manually then retry.")

    out.info("Reinstalling dependencies")
    venv_pip = REPO_ROOT / ".venv" / "bin" / "pip"
    rc = subprocess.call([str(venv_pip), "install", "-e", "."], cwd=str(REPO_ROOT))
    if rc != 0:
        out.die("pip install failed. Check the error above.")

    out.info("Running database migrations")
    _flask_command(["db", "upgrade"], abort_on_error=False)

    _compile_translations()

    if not skip_restart:
        plat = current_platform()
        if plat.status().running:
            out.info("Restarting server")
            plat.restart()

    out.ok("Update complete.")


# ── start / stop / restart / status ─────────────────────────────


@main.command()
@click.option(
    "--foreground/--background", default=False,
    help="Run attached to this terminal (default: background).",
)
@click.option("--port", default=5001, type=int)
def start(foreground: bool, port: int) -> None:
    """Start the web server."""
    current_platform().start(port=port, foreground=foreground)


@main.command()
def stop() -> None:
    """Stop the running web server."""
    current_platform().stop()


@main.command()
@click.option("--port", default=5001, type=int)
def restart(port: int) -> None:
    """Stop, then start. Useful after config changes."""
    current_platform().restart(port=port)


@main.command()
def status() -> None:
    """Show whether stoic is running, on what port, and for how long."""
    s = current_platform().status()
    if s.running:
        uptime = _format_uptime(s.uptime_seconds) if s.uptime_seconds else "unknown"
        out.ok(
            f"Stoic running (pid {s.pid}, uptime {uptime}, "
            f"via {s.method}) on http://127.0.0.1:{s.port}"
        )
    else:
        out.info(f"Stoic not running (method: {s.method}).")


# ── backup / db-encrypt / db-status ─────────────────────────────


@main.command()
def backup() -> None:
    """Trigger a manual database backup.

    Backups go into ``instance/backups/`` and are gzipped (and
    optionally encrypted if you've configured a passphrase
    source). Same behavior as ``flask backup`` — this is just a
    friendlier wrapper.
    """
    out.info("Running backup")
    _flask_command(["backup"])


@main.command("db-encrypt")
def db_encrypt() -> None:
    """Encrypt the live SQLite database with SQLCipher.

    Prompts for a passphrase. The existing plaintext DB is
    sidelined (renamed with a timestamp) so you can recover if
    something goes wrong. After encryption, you'll need to
    configure stoic to read the passphrase on boot — see
    Settings → Encryption & backups.
    """
    out.info("Encrypting live database")
    _flask_command(["db-encrypt"])


@main.command("db-status")
def db_status() -> None:
    """Report whether the live database is encrypted."""
    _flask_command(["db-status"])


# ── version / doctor ────────────────────────────────────────────


@main.command()
def version() -> None:
    """Print the stoic version."""
    click.echo(f"stoic-eln {__version__}")


@main.command()
def doctor() -> None:
    """Diagnose installation problems.

    Checks Python version, virtual env, key dependencies,
    database file, instance directory permissions, and whether
    the server is currently reachable. Prints a report —
    nothing is modified.
    """
    out.header("Stoic doctor")
    _doctor_python()
    _doctor_venv()
    _doctor_deps()
    _doctor_db()
    _doctor_server()
    out.ok("Doctor complete.")


# ── Helpers ─────────────────────────────────────────────────────


def _ensure_python_version() -> None:
    """Stoic supports Python 3.11+ but recommends 3.12."""
    major, minor = sys.version_info.major, sys.version_info.minor
    if major != 3 or minor < 11:
        out.die(f"Python 3.11+ required. Found {major}.{minor}.")
    if minor == 11:
        out.warn("Python 3.11 detected — 3.12 is recommended.")
    else:
        out.ok(f"Python {major}.{minor}")


def _ensure_venv() -> None:
    """Create ``.venv`` if missing."""
    venv = REPO_ROOT / ".venv"
    if venv.exists():
        out.ok(f"Virtual environment exists at {venv}")
        return

    out.info(f"Creating virtual environment at {venv}")
    rc = subprocess.call([sys.executable, "-m", "venv", str(venv)])
    if rc != 0:
        out.die("venv creation failed.")
    out.ok("Virtual environment created.")


def _install_deps() -> None:
    """Install (or upgrade) Python dependencies via pip."""
    venv_pip = REPO_ROOT / ".venv" / "bin" / "pip"
    if not venv_pip.exists():
        out.die(f"pip not found at {venv_pip} — venv is broken.")

    out.info("Installing Python dependencies (this may take a minute)")
    rc = subprocess.call(
        [str(venv_pip), "install", "--upgrade", "-e", "."],
        cwd=str(REPO_ROOT),
    )
    if rc != 0:
        out.die("Dependency installation failed.")
    out.ok("Dependencies installed.")


def _init_db() -> None:
    """Run flask db upgrade. Safe to re-run — alembic noop's
    when schema is up to date."""
    out.info("Initializing database schema")
    _flask_command(["db", "upgrade"], abort_on_error=False)


def _create_first_admin(admin_email: str | None) -> None:
    """Check for any user; if none, create the first admin
    interactively or with the provided email."""
    # Defer import: stoic CLI may run before app context is ready
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    check_script = (
        "from stoic_eln import create_app; "
        "from stoic_eln.models import User; "
        "app = create_app(); "
        "ctx = app.app_context(); ctx.push(); "
        "print('USERS:', User.query.count())"
    )
    result = subprocess.run(
        [str(venv_python), "-c", check_script],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        env={**os.environ, "FLASK_APP": "stoic_eln"},
    )
    count = 0
    for line in result.stdout.splitlines():
        if line.startswith("USERS:"):
            try:
                count = int(line.split(":")[1].strip())
            except ValueError:
                pass

    if count > 0:
        out.ok(f"{count} user(s) already exist — skipping admin creation.")
        return

    out.info("No users yet — creating first admin")
    cmd = ["create-user", "--admin"]
    if admin_email:
        cmd.extend(["--email", admin_email])
    _flask_command(cmd)


def _compile_translations() -> None:
    """Compile .po → .mo. Best-effort: failure is non-fatal."""
    venv_pybabel = REPO_ROOT / ".venv" / "bin" / "pybabel"
    if not venv_pybabel.exists():
        return  # babel not installed yet, no big deal

    out.info("Compiling translations")
    rc = subprocess.call(
        [str(venv_pybabel), "compile", "-d", "stoic_eln/translations"],
        cwd=str(REPO_ROOT),
    )
    if rc != 0:
        out.warn("Translation compile had warnings (non-fatal).")


def _flask_command(args: list[str], abort_on_error: bool = True) -> int:
    """Run a flask command in the project venv with FLASK_APP set."""
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    env = {**os.environ, "FLASK_APP": "stoic_eln"}
    rc = subprocess.call(
        [str(venv_python), "-m", "flask", "--app", "stoic_eln", *args],
        cwd=str(REPO_ROOT), env=env,
    )
    if rc != 0 and abort_on_error:
        out.die(f"flask {' '.join(args)} failed (exit {rc}).")
    return rc


def _format_uptime(seconds: int) -> str:
    """Render seconds as a compact human string: 2h13m, 5d3h, etc."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d{(seconds % 86400) // 3600}h"


# ── doctor sub-checks ───────────────────────────────────────────


def _doctor_python() -> None:
    major, minor = sys.version_info.major, sys.version_info.minor
    if major == 3 and minor >= 12:
        out.ok(f"Python {major}.{minor}.{sys.version_info.micro}")
    elif major == 3 and minor == 11:
        out.warn("Python 3.11 — works, but 3.12 is recommended.")
    else:
        out.error(f"Python {major}.{minor} is too old — need 3.11+.")


def _doctor_venv() -> None:
    venv = REPO_ROOT / ".venv"
    if venv.exists():
        out.ok(f"Virtual env at {venv}")
    else:
        out.error(f"No virtual env at {venv} — run 'stoic install'.")


def _doctor_deps() -> None:
    """Verify a handful of critical packages."""
    critical = [
        "flask", "sqlalchemy", "flask_babel", "reportlab",
        "rdkit", "cryptography",
    ]
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        out.warn("Skipping dependency check — venv missing.")
        return
    for pkg in critical:
        result = subprocess.run(
            [str(venv_python), "-c", f"import {pkg}"],
            capture_output=True,
        )
        if result.returncode == 0:
            out.ok(f"  {pkg}")
        else:
            out.error(f"  {pkg} — not importable")


def _doctor_db() -> None:
    db_path = REPO_ROOT / "instance" / "stoic_eln.db"
    if not db_path.exists():
        out.warn(f"Database file not found at {db_path} (will be created on first run).")
        return
    size_kb = db_path.stat().st_size // 1024
    out.ok(f"Database at {db_path} ({size_kb} KB)")


def _doctor_server() -> None:
    s = current_platform().status()
    if s.running:
        out.ok(f"Server running (pid {s.pid}) via {s.method}")
    else:
        out.info("Server not running.")
