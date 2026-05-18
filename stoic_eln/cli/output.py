"""Output helpers for the stoic CLI.

Centralizes how success/info/warn/error messages are formatted
and colored. Subcommands import ``ok``, ``info``, ``warn``,
``error``, ``die`` and use them instead of bare ``print()``
or ``click.echo()``.

Colors are auto-detected: enabled only if stdout is a terminal,
disabled when piped to a file or run under CI. Set
``STOIC_NO_COLOR=1`` to disable explicitly.

The rationale for not just using click.secho everywhere is so
that we have a single place to change the tone (and to add
i18n later if we want — though for a CLI used mostly by
sysadmins the convention is English-only).
"""

from __future__ import annotations

import os
import sys

import click

# ANSI escape codes — used only when colors are enabled.
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BLUE = "\033[34m"


def _colors_enabled() -> bool:
    if os.environ.get("STOIC_NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def _wrap(text: str, code: str) -> str:
    if not _colors_enabled():
        return text
    return f"{code}{text}{_RESET}"


def ok(msg: str) -> None:
    """Success message. Use for: install complete, restart done,
    DB upgraded, etc."""
    prefix = _wrap("✓", _GREEN)
    click.echo(f"{prefix} {msg}")


def info(msg: str) -> None:
    """Informational message. Use for: progress updates, 'fetching X',
    'installing Y'. Should be common during normal flow."""
    prefix = _wrap("→", _BLUE)
    click.echo(f"{prefix} {msg}")


def warn(msg: str) -> None:
    """Warning. Something unusual but recoverable.

    Examples: 'Python 3.11 detected, recommend 3.12', 'No daemon
    integration available on this platform, falling back to nohup'.
    """
    prefix = _wrap("⚠", _YELLOW)
    click.echo(f"{prefix} {msg}", err=True)


def error(msg: str) -> None:
    """Error message. Doesn't exit. Use when you want to print
    multiple errors before bailing, or in a non-fatal context."""
    prefix = _wrap("✗", _RED)
    click.echo(f"{prefix} {msg}", err=True)


def die(msg: str, code: int = 1) -> None:
    """Print an error and exit. Use for fatal conditions:
    missing dependencies, can't start, permission denied, etc."""
    error(msg)
    sys.exit(code)


def header(msg: str) -> None:
    """Section header. Use sparingly — for the start of a
    multi-step operation like ``install`` or ``doctor``."""
    line = _wrap(f"━━ {msg} ━━", _BOLD)
    click.echo(line)


def dim(text: str) -> str:
    """Return ``text`` wrapped in dim ANSI codes (used inline)."""
    return _wrap(text, _DIM)


def bold(text: str) -> str:
    """Return ``text`` wrapped in bold ANSI codes (used inline)."""
    return _wrap(text, _BOLD)
