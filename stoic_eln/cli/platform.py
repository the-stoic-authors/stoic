"""Platform detection and service-management abstraction.

The stoic CLI is cross-platform: it has to manage a long-running
Flask process across macOS (launchd), Debian/Raspbian (systemd
user), and any other Unix that has neither. This module
abstracts those differences behind a uniform interface.

Usage::

    from stoic_eln.cli.platform import current
    plat = current()
    plat.install_daemon()   # one-time setup
    plat.start()
    plat.stop()
    plat.is_running()       # -> bool
    plat.status()           # -> dict

Each Platform class encapsulates one daemon manager. ``current()``
returns the most capable one available at runtime.
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


# The PID file is the lowest-common-denominator way to ask "is
# stoic running?" — used by all platforms. Lives in the repo
# root (next to pyproject.toml) so it's discoverable without
# extra config.
def _repo_root() -> Path:
    """Return the project root directory.

    Resolved by walking up from this file until we find
    pyproject.toml. Falls back to current working directory.
    """
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _repo_root()
PID_FILE = REPO_ROOT / "instance" / "stoic.pid"
LOG_FILE = REPO_ROOT / "instance" / "stoic.log"


@dataclass
class Status:
    """Lightweight snapshot of stoic's runtime state."""

    running: bool
    pid: int | None = None
    uptime_seconds: int | None = None
    port: int = 5001
    method: str = "unknown"  # "launchd", "systemd", "nohup", "foreground"


class Platform(ABC):
    """Abstract base for platform-specific service management.

    Subclasses implement start/stop/status for one daemon manager
    (launchd on Mac, systemd on Linux, or a generic PID-file
    fallback). The CLI never instantiates these directly — it
    calls ``current()`` and uses whatever comes back.
    """

    name: str = "generic"

    @abstractmethod
    def start(self, port: int = 5001, foreground: bool = False) -> None:
        """Start the Flask server.

        With ``foreground=True``, blocks the terminal until Ctrl+C
        (useful for `stoic start --foreground` and during install
        for debugging). Otherwise runs as a daemon — exact
        mechanism depends on the platform.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop a running stoic process. Idempotent: no error if
        already stopped."""
        ...

    @abstractmethod
    def status(self) -> Status:
        """Report whether stoic is running, plus diagnostics."""
        ...

    def restart(self, port: int = 5001) -> None:
        """Stop, then start. Default implementation works for any
        platform; subclasses can override if they have a
        ``systemctl restart``-style atomic primitive."""
        self.stop()
        # Tiny grace period so the port releases cleanly.
        time.sleep(0.5)
        self.start(port=port)

    def install_daemon(self, port: int = 5001) -> None:
        """Register stoic as a persistent service that survives
        reboots and user logouts.

        On macOS this writes a launchd plist and loads it.
        On Linux this writes a systemd user unit and enables it.
        On the generic fallback, this is a no-op (you'd just
        use ``stoic start`` manually).
        """
        # Default: no-op for fallback. Subclasses override.
        from stoic_eln.cli.output import warn

        warn(
            f"Daemon installation not supported on {self.name}. "
            f"Use 'stoic start' manually after boot, or set up "
            f"a custom service unit."
        )

    def uninstall_daemon(self) -> None:
        """Reverse of install_daemon. Removes service file and
        unloads/disables it. Default: no-op."""
        ...


# ── Generic (PID-file) implementation ───────────────────────────


class GenericPlatform(Platform):
    """Last-resort implementation using a PID file + nohup.

    Used when launchd and systemd are both unavailable. Survives
    terminal close but NOT system reboots — you'd have to
    re-run ``stoic start`` on every boot.
    """

    name = "generic"

    def _read_pid(self) -> int | None:
        if not PID_FILE.exists():
            return None
        try:
            return int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            return None

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)  # Signal 0 = "check if exists"
        except OSError:
            return False
        return True

    def start(self, port: int = 5001, foreground: bool = False) -> None:
        from stoic_eln.cli.output import die, info, ok, warn

        existing = self._read_pid()
        if existing and self._pid_alive(existing):
            warn(f"Stoic already running (pid {existing}). Use 'stoic restart' to restart.")
            return

        venv_python = REPO_ROOT / ".venv" / "bin" / "python"
        if not venv_python.exists():
            die(f"Virtual environment not found at {venv_python}. Run 'stoic install' first.")

        env = os.environ.copy()
        env["FLASK_APP"] = "stoic_eln"

        if foreground:
            info(f"Starting Stoic in foreground on port {port} (Ctrl+C to stop)")
            os.execve(
                str(venv_python),
                [
                    str(venv_python),
                    "-m",
                    "flask",
                    "--app",
                    "stoic_eln",
                    "run",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                env,
            )

        # Background mode: nohup-style detach. Pipes stdout/stderr
        # to a log file so we can debug failed starts.
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "ab") as log_fh:
            proc = subprocess.Popen(
                [
                    str(venv_python),
                    "-m",
                    "flask",
                    "--app",
                    "stoic_eln",
                    "run",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # detach from terminal
                env=env,
                cwd=str(REPO_ROOT),
            )

        PID_FILE.write_text(str(proc.pid))
        # Give the server 1.5s to either boot or crash, then verify.
        time.sleep(1.5)
        if not self._pid_alive(proc.pid):
            die(
                f"Stoic failed to start. See {LOG_FILE} for the error. "
                f"Last 5 lines:\n" + _tail(LOG_FILE, 5),
            )
        ok(f"Stoic started (pid {proc.pid}) on http://127.0.0.1:{port}")

    def stop(self) -> None:
        from stoic_eln.cli.output import info, ok, warn

        pid = self._read_pid()
        if pid is None:
            warn("Stoic doesn't seem to be running (no PID file).")
            return
        if not self._pid_alive(pid):
            info("Stale PID file — cleaning up.")
            PID_FILE.unlink(missing_ok=True)
            return

        os.kill(pid, signal.SIGTERM)
        # Wait up to 5 seconds for clean shutdown
        for _ in range(50):
            if not self._pid_alive(pid):
                break
            time.sleep(0.1)
        else:
            warn(f"Process {pid} didn't exit on SIGTERM after 5s. Sending SIGKILL.")
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.2)

        PID_FILE.unlink(missing_ok=True)
        ok(f"Stoic stopped (pid {pid}).")

    def status(self) -> Status:
        pid = self._read_pid()
        if pid is None or not self._pid_alive(pid):
            return Status(running=False, method=self.name)

        # Best-effort uptime via ps. Works on macOS and Linux.
        uptime = None
        try:
            out = subprocess.check_output(
                ["ps", "-o", "etimes=", "-p", str(pid)],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            uptime = int(out.strip())
        except (subprocess.CalledProcessError, ValueError):
            pass

        return Status(running=True, pid=pid, uptime_seconds=uptime, method=self.name)


# ── macOS / launchd implementation ──────────────────────────────


PLIST_LABEL = "com.stoic.eln"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


class MacOSPlatform(GenericPlatform):
    """macOS-specific: registers stoic as a launchd LaunchAgent so
    it survives login/logout cycles (still per-user, not
    system-wide — that's intentional, see Mac multi-user note in
    the docs).
    """

    name = "macos"

    def install_daemon(self, port: int = 5001) -> None:
        from stoic_eln.cli.output import die, info, ok

        venv_python = REPO_ROOT / ".venv" / "bin" / "python"
        if not venv_python.exists():
            die(f"Virtual environment not found at {venv_python}. Run 'stoic install' first.")

        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Template kept simple on purpose: KeepAlive=true means
        # launchd restarts stoic if it crashes; RunAtLoad=true
        # starts it at login. No EnvironmentVariables block so
        # the user can set STOIC_BACKUP_PASSPHRASE in their
        # shell rc if they want env-mode encryption.
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>WorkingDirectory</key>
    <string>{REPO_ROOT}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{venv_python}</string>
        <string>-m</string>
        <string>flask</string>
        <string>--app</string>
        <string>stoic_eln</string>
        <string>run</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>{port}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>FLASK_APP</key>
        <string>stoic_eln</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>
</dict>
</plist>
"""
        PLIST_PATH.write_text(plist)
        info(f"Wrote LaunchAgent plist to {PLIST_PATH}")

        # Load it
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False, capture_output=True)
        result = subprocess.run(
            ["launchctl", "load", str(PLIST_PATH)], check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            die(f"launchctl load failed: {result.stderr.strip()}")

        ok(
            "Stoic registered as launchd service. It will start "
            "automatically when you log in. Use 'stoic stop' / 'stoic start' "
            "to control it."
        )

    def uninstall_daemon(self) -> None:
        from stoic_eln.cli.output import info, ok

        if not PLIST_PATH.exists():
            info("No launchd registration found, nothing to remove.")
            return

        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False, capture_output=True)
        PLIST_PATH.unlink()
        ok("Removed launchd registration.")

    def start(self, port: int = 5001, foreground: bool = False) -> None:
        """Prefer launchctl if registered; otherwise fall back to
        generic nohup-style start."""
        if PLIST_PATH.exists() and not foreground:
            from stoic_eln.cli.output import info, ok

            result = subprocess.run(
                ["launchctl", "start", PLIST_LABEL],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                time.sleep(1.0)
                ok(f"Stoic started via launchd on http://127.0.0.1:{port}")
                return
            info(f"launchctl start failed ({result.stderr.strip()}), trying direct start.")

        # Fallback: parent implementation
        super().start(port=port, foreground=foreground)

    def stop(self) -> None:
        if PLIST_PATH.exists():
            from stoic_eln.cli.output import ok

            subprocess.run(["launchctl", "stop", PLIST_LABEL], check=False, capture_output=True)
            time.sleep(0.5)
            PID_FILE.unlink(missing_ok=True)
            ok("Stoic stopped via launchd.")
            return
        super().stop()

    def status(self) -> Status:
        if PLIST_PATH.exists():
            # Query launchctl for the service state
            result = subprocess.run(
                ["launchctl", "list", PLIST_LABEL],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                # Parse "PID" from output like:
                # "PID" = 12345;
                pid = None
                for line in result.stdout.splitlines():
                    if '"PID"' in line:
                        try:
                            pid = int(line.split("=")[1].strip().rstrip(";").strip())
                        except (ValueError, IndexError):
                            pass
                        break
                if pid:
                    return Status(running=True, pid=pid, method="launchd")
                # Registered but not running
                return Status(running=False, method="launchd")
        return super().status()


# ── Linux / systemd user implementation ─────────────────────────


SYSTEMD_UNIT_NAME = "stoic-eln.service"
SYSTEMD_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
SYSTEMD_UNIT_PATH = SYSTEMD_UNIT_DIR / SYSTEMD_UNIT_NAME


class LinuxSystemdPlatform(GenericPlatform):
    """Linux with systemd user services (most modern distros:
    Debian 10+, Ubuntu 18.04+, Raspbian Buster+, Arch, Fedora).

    Uses ``systemctl --user`` rather than system-wide units. The
    benefit: no sudo needed for install, and stoic runs as the
    installing user with their PATH. The cost: stoic only starts
    when that user logs in (unless ``loginctl enable-linger
    <user>`` is run, which we explain in the docs).
    """

    name = "linux-systemd"

    def install_daemon(self, port: int = 5001) -> None:
        from stoic_eln.cli.output import die, info, ok

        venv_python = REPO_ROOT / ".venv" / "bin" / "python"
        if not venv_python.exists():
            die(f"Virtual environment not found at {venv_python}. Run 'stoic install' first.")

        SYSTEMD_UNIT_DIR.mkdir(parents=True, exist_ok=True)

        unit = f"""\
[Unit]
Description=Stoic ELN (electronic lab notebook)
After=network.target

[Service]
Type=simple
WorkingDirectory={REPO_ROOT}
Environment="FLASK_APP=stoic_eln"
ExecStart={venv_python} -m flask --app stoic_eln run --host 127.0.0.1 --port {port}
Restart=on-failure
RestartSec=5
StandardOutput=append:{LOG_FILE}
StandardError=append:{LOG_FILE}

[Install]
WantedBy=default.target
"""
        SYSTEMD_UNIT_PATH.write_text(unit)
        info(f"Wrote systemd unit to {SYSTEMD_UNIT_PATH}")

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", SYSTEMD_UNIT_NAME], check=True)
        subprocess.run(["systemctl", "--user", "start", SYSTEMD_UNIT_NAME], check=True)

        ok(
            "Stoic registered as systemd user service. To make it "
            "start without you logging in, run:\n"
            "  sudo loginctl enable-linger $USER"
        )

    def uninstall_daemon(self) -> None:
        from stoic_eln.cli.output import info, ok

        if not SYSTEMD_UNIT_PATH.exists():
            info("No systemd unit found, nothing to remove.")
            return

        subprocess.run(
            ["systemctl", "--user", "stop", SYSTEMD_UNIT_NAME], check=False, capture_output=True
        )
        subprocess.run(
            ["systemctl", "--user", "disable", SYSTEMD_UNIT_NAME], check=False, capture_output=True
        )
        SYSTEMD_UNIT_PATH.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        ok("Removed systemd registration.")

    def start(self, port: int = 5001, foreground: bool = False) -> None:
        if SYSTEMD_UNIT_PATH.exists() and not foreground:
            from stoic_eln.cli.output import ok

            subprocess.run(
                ["systemctl", "--user", "start", SYSTEMD_UNIT_NAME],
                check=True,
            )
            time.sleep(1.0)
            ok(f"Stoic started via systemd on http://127.0.0.1:{port}")
            return
        super().start(port=port, foreground=foreground)

    def stop(self) -> None:
        if SYSTEMD_UNIT_PATH.exists():
            from stoic_eln.cli.output import ok

            subprocess.run(
                ["systemctl", "--user", "stop", SYSTEMD_UNIT_NAME],
                check=False,
            )
            ok("Stoic stopped via systemd.")
            return
        super().stop()

    def status(self) -> Status:
        if SYSTEMD_UNIT_PATH.exists():
            result = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    SYSTEMD_UNIT_NAME,
                    "--property=ActiveState,MainPID",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            active = False
            pid = None
            for line in result.stdout.splitlines():
                if line.startswith("ActiveState="):
                    active = line.split("=", 1)[1] == "active"
                elif line.startswith("MainPID="):
                    try:
                        pid = int(line.split("=", 1)[1])
                        if pid == 0:
                            pid = None
                    except ValueError:
                        pass
            if active and pid:
                return Status(running=True, pid=pid, method="systemd")
            return Status(running=False, method="systemd")
        return super().status()


# ── Dispatcher ─────────────────────────────────────────────────────


def current() -> Platform:
    """Return the best Platform implementation for this OS.

    Detection order:
    1. macOS (Darwin) → MacOSPlatform
    2. Linux + systemctl available → LinuxSystemdPlatform
    3. Anything else → GenericPlatform (PID-file fallback)
    """
    system = platform.system()
    if system == "Darwin":
        return MacOSPlatform()
    if system == "Linux" and shutil.which("systemctl"):
        return LinuxSystemdPlatform()
    return GenericPlatform()


# ── Internal helpers ──────────────────────────────────────────────


def _tail(path: Path, n: int) -> str:
    """Return the last n lines of a text file, best-effort."""
    if not path.exists():
        return "(no log file)"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return "(could not read log)"
