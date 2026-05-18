"""Stoic ELN — command-line interface.

This package provides the top-level ``stoic`` command, exposed
through pyproject.toml as a Python entry point. It's the
operator-facing wrapper for installation, updates, service
management, backups, and diagnostics — the things a sysadmin
(or a chemist running Stoic on their own Mac) needs to do
without poking inside the Flask CLI.

Architecture:

- ``stoic_eln.cli.main`` is the click entry point. It dispatches
  to subcommand modules.
- Each subcommand lives in its own module
  (``install.py``, ``update.py``, etc.) and is registered with
  ``@main.command(...)``.
- Platform detection (macOS launchd vs Linux systemd vs fallback)
  is centralized in ``stoic_eln.cli.platform``. Subcommands ask
  ``platform.current()`` and get back a Platform object that
  exposes the right primitives for that OS.
- All output goes through ``stoic_eln.cli.output`` (success/info/warn/error
  helpers). Keeps tone consistent and makes future i18n trivial.
"""

from __future__ import annotations

from stoic_eln.cli.main import main

__all__ = ["main"]
