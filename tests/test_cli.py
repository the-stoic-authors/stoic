"""Tests for the stoic CLI (patch 15.1).

Covers the click command registration, help output, platform
detection, and a few unit-level checks for output helpers. Full
end-to-end coverage (actually starting stoic, hitting launchd /
systemd) isn't here — those need a real OS daemon manager and
should be exercised manually with ``stoic install --daemon`` /
``stoic start`` on a real machine.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from stoic_eln import __version__
from stoic_eln.cli import output as out
from stoic_eln.cli.main import main as cli_main
from stoic_eln.cli.platform import (
    GenericPlatform,
    LinuxSystemdPlatform,
    MacOSPlatform,
    Status,
    current,
)


# ── Command registration & help ─────────────────────────────────


def test_cli_main_registers_all_commands():
    """All 11 documented commands are wired up."""
    expected = {
        "install",
        "update",
        "start",
        "stop",
        "restart",
        "status",
        "backup",
        "db-encrypt",
        "db-status",
        "version",
        "doctor",
    }
    actual = set(cli_main.commands.keys())
    assert actual == expected, f"Missing/extra: {actual.symmetric_difference(expected)}"


def test_cli_help_lists_commands():
    """`stoic --help` mentions every subcommand."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("install", "update", "start", "stop", "status", "backup", "doctor", "version"):
        assert cmd in result.output, f"'{cmd}' missing from --help"


def test_cli_version_command():
    """`stoic version` prints the current version."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_version_flag_works():
    """`stoic --version` also works (click built-in)."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_install_help_documents_options():
    """`stoic install --help` documents --daemon, --port, --admin-email."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["install", "--help"])
    assert result.exit_code == 0
    assert "--daemon" in result.output
    assert "--port" in result.output
    assert "--admin-email" in result.output


def test_start_help_documents_foreground():
    """`stoic start --help` documents --foreground."""
    runner = CliRunner()
    result = runner.invoke(cli_main, ["start", "--help"])
    assert result.exit_code == 0
    assert "--foreground" in result.output or "--background" in result.output


# ── Platform detection ──────────────────────────────────────────


def test_current_returns_macos_on_darwin():
    """On macOS, current() picks MacOSPlatform."""
    with patch("stoic_eln.cli.platform.platform.system", return_value="Darwin"):
        p = current()
        assert isinstance(p, MacOSPlatform)
        assert p.name == "macos"


def test_current_returns_systemd_on_linux_with_systemctl():
    """On Linux with systemctl present, current() picks LinuxSystemdPlatform."""
    with patch("stoic_eln.cli.platform.platform.system", return_value="Linux"):
        with patch("stoic_eln.cli.platform.shutil.which", return_value="/bin/systemctl"):
            p = current()
            assert isinstance(p, LinuxSystemdPlatform)
            assert p.name == "linux-systemd"


def test_current_returns_generic_when_no_systemd():
    """On Linux without systemctl, falls back to GenericPlatform."""
    with patch("stoic_eln.cli.platform.platform.system", return_value="Linux"):
        with patch("stoic_eln.cli.platform.shutil.which", return_value=None):
            p = current()
            assert isinstance(p, GenericPlatform)
            assert p.name == "generic"


def test_current_returns_generic_on_unknown_os():
    """Anything other than Darwin/Linux gets the generic fallback."""
    with patch("stoic_eln.cli.platform.platform.system", return_value="FreeBSD"):
        p = current()
        assert isinstance(p, GenericPlatform)


# ── GenericPlatform PID-file logic ──────────────────────────────


def test_generic_status_returns_not_running_when_no_pid_file(tmp_path, monkeypatch):
    """No PID file → status reports not running."""
    monkeypatch.setattr("stoic_eln.cli.platform.PID_FILE", tmp_path / "nope.pid")
    p = GenericPlatform()
    s = p.status()
    assert s.running is False
    assert s.pid is None


def test_generic_status_handles_stale_pid_file(tmp_path, monkeypatch):
    """PID file points to a dead process → status reports not running."""
    pid_file = tmp_path / "stoic.pid"
    pid_file.write_text("99999")  # Almost certainly dead PID
    monkeypatch.setattr("stoic_eln.cli.platform.PID_FILE", pid_file)
    p = GenericPlatform()
    s = p.status()
    assert s.running is False


def test_generic_status_detects_live_process(tmp_path, monkeypatch):
    """PID of an actually-running process → status reports running."""
    pid_file = tmp_path / "stoic.pid"
    pid_file.write_text(str(os.getpid()))  # Use our own PID
    monkeypatch.setattr("stoic_eln.cli.platform.PID_FILE", pid_file)
    p = GenericPlatform()
    s = p.status()
    assert s.running is True
    assert s.pid == os.getpid()


def test_generic_status_method_field(tmp_path, monkeypatch):
    """Status.method correctly reports the platform name."""
    monkeypatch.setattr("stoic_eln.cli.platform.PID_FILE", tmp_path / "nope.pid")
    p = GenericPlatform()
    assert p.status().method == "generic"


# ── Output helpers ──────────────────────────────────────────────


def test_output_no_color_when_not_tty(monkeypatch, capsys):
    """When STOIC_NO_COLOR is set, no ANSI codes in output."""
    monkeypatch.setenv("STOIC_NO_COLOR", "1")
    out.ok("test message")
    captured = capsys.readouterr()
    # No ANSI escape codes (they start with ESC = \x1b)
    assert "\x1b" not in captured.out
    assert "test message" in captured.out


def test_output_ok_writes_to_stdout(monkeypatch, capsys):
    monkeypatch.setenv("STOIC_NO_COLOR", "1")
    out.ok("yes")
    captured = capsys.readouterr()
    assert "yes" in captured.out


def test_output_warn_writes_to_stderr(monkeypatch, capsys):
    """Warnings should go to stderr so they don't pollute stdout
    when piping the output of stoic to another program."""
    monkeypatch.setenv("STOIC_NO_COLOR", "1")
    out.warn("careful")
    captured = capsys.readouterr()
    assert "careful" in captured.err
    assert captured.out == ""


def test_output_error_writes_to_stderr(monkeypatch, capsys):
    monkeypatch.setenv("STOIC_NO_COLOR", "1")
    out.error("nope")
    captured = capsys.readouterr()
    assert "nope" in captured.err


def test_output_die_exits_with_code(monkeypatch):
    monkeypatch.setenv("STOIC_NO_COLOR", "1")
    with pytest.raises(SystemExit) as exc_info:
        out.die("fatal")
    assert exc_info.value.code == 1


# ── Status dataclass ────────────────────────────────────────────


def test_status_defaults():
    """Status with running=False has sensible defaults."""
    s = Status(running=False)
    assert s.pid is None
    assert s.uptime_seconds is None
    assert s.port == 5001
    assert s.method == "unknown"


def test_status_with_full_data():
    s = Status(running=True, pid=12345, uptime_seconds=3600, port=5000, method="launchd")
    assert s.running
    assert s.pid == 12345
    assert s.uptime_seconds == 3600


# ── Format uptime helper ────────────────────────────────────────


def test_format_uptime_seconds():
    from stoic_eln.cli.main import _format_uptime

    assert _format_uptime(45) == "45s"


def test_format_uptime_minutes():
    from stoic_eln.cli.main import _format_uptime

    assert _format_uptime(120) == "2m"


def test_format_uptime_hours():
    from stoic_eln.cli.main import _format_uptime

    assert _format_uptime(7320) == "2h2m"  # 2*3600 + 2*60


def test_format_uptime_days():
    from stoic_eln.cli.main import _format_uptime

    assert _format_uptime(90000) == "1d1h"  # 86400 + 3600
