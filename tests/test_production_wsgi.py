"""Tests for the production deployment infrastructure (Patch A).

The patch's goal is to make Stoic runnable behind gunicorn without
firing the nightly backup scheduler N times (one per worker). The
fix is structural:

- ``create_app()`` gains a ``start_scheduler`` keyword (default True
  to preserve dev/script behaviour)
- ``wsgi.py`` calls ``create_app(start_scheduler=False)``, so each
  worker process skips scheduler init
- ``gunicorn.conf.py``'s ``when_ready`` hook is the SINGLE place
  that boots an app with ``start_scheduler=True``, and it runs only
  in the master process

These tests verify the contract at the Python-API level. The hook
itself (running inside gunicorn's master) needs end-to-end
validation on a real Linux server — out of scope here.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch


# ── create_app honours the start_scheduler flag ───────────────────


def test_create_app_default_calls_init_scheduler():
    """Default behaviour (used by `flask run`, scripts, migrations)
    must still call init_scheduler so the dev experience is
    unchanged. The scheduler itself short-circuits under TESTING,
    so we mock to observe the call."""
    from stoic_eln import create_app
    from stoic_eln.config import TestingConfig

    with patch("stoic_eln.services.scheduler.init_scheduler") as mock_init:
        create_app(TestingConfig)
        assert mock_init.called, "init_scheduler must be called by default"


def test_create_app_with_start_scheduler_false_does_not_call_init():
    """wsgi.py uses this path so workers don't each spawn a
    scheduler. Without it, N workers = N nightly backups."""
    from stoic_eln import create_app
    from stoic_eln.config import TestingConfig

    with patch("stoic_eln.services.scheduler.init_scheduler") as mock_init:
        create_app(TestingConfig, start_scheduler=False)
        assert not mock_init.called, "init_scheduler must NOT be called when start_scheduler=False"


# ── wsgi.app is importable and configured for workers ─────────────


def _load_wsgi_module(name: str = "wsgi_under_test"):
    """Load wsgi.py from the repo root by file path, bypassing
    sys.modules caching and any sys.path quirks. Each call produces
    a freshly executed module — exactly what we need to assert on
    side effects (which happen at module top level)."""
    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    wsgi_path = repo_root / "wsgi.py"
    assert wsgi_path.exists(), f"expected wsgi.py at {wsgi_path}"

    spec = importlib.util.spec_from_file_location(name, str(wsgi_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wsgi_module_imports_and_provides_app(tmp_path, monkeypatch):
    """The wsgi entrypoint must produce a usable Flask app instance.

    We force a minimal config via env vars so that production class
    requirements (e.g. mandatory SECRET_KEY) are satisfied without
    needing a real deployment.
    """
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-key-for-wsgi-import")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/wsgi-test.db")

    wsgi = _load_wsgi_module("wsgi_import_test")

    assert hasattr(wsgi, "app"), "wsgi must expose an `app` attribute"
    # Duck-typing for Flask app: it must have a wsgi_app method
    assert callable(getattr(wsgi.app, "wsgi_app", None))


def test_wsgi_app_does_not_start_scheduler(tmp_path, monkeypatch):
    """When wsgi.py is imported (which is what gunicorn does for
    each worker), no scheduler thread should be running."""
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-key-for-wsgi-no-scheduler")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/wsgi-no-sched.db")

    with patch("stoic_eln.services.scheduler.init_scheduler") as mock_init:
        # Fresh execution of wsgi.py with the mock already in place
        _load_wsgi_module("wsgi_no_scheduler_test")
        assert not mock_init.called, (
            "wsgi must call create_app with start_scheduler=False so the scheduler does NOT start"
        )


# ── gunicorn.conf.py is syntactically valid + reads env ───────────


def test_gunicorn_config_module_is_importable():
    """The config file is loaded by gunicorn via -c. It must at
    minimum import cleanly and expose the canonical settings."""
    spec = importlib.util.spec_from_file_location(
        "gunicorn_conf_under_test",
        "gunicorn.conf.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Required gunicorn settings
    assert hasattr(module, "bind")
    assert hasattr(module, "workers")
    assert hasattr(module, "timeout")
    assert callable(module.when_ready), "when_ready must be callable"


def test_gunicorn_config_honours_env_vars(monkeypatch):
    """The operator changes STOIC_BIND / STOIC_WORKERS without
    editing the file. Ensure those env vars actually flow through."""
    monkeypatch.setenv("STOIC_BIND", "0.0.0.0:8888")
    monkeypatch.setenv("STOIC_WORKERS", "4")
    monkeypatch.setenv("STOIC_TIMEOUT", "60")

    spec = importlib.util.spec_from_file_location(
        "gunicorn_conf_env_under_test",
        "gunicorn.conf.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.bind == "0.0.0.0:8888"
    assert module.workers == 4
    assert module.timeout == 60


def test_gunicorn_config_defaults_to_safe_bind():
    """A fresh install must NOT expose Stoic on the LAN by default.
    Operator opts in explicitly via STOIC_BIND."""
    import os

    # Clean env: no STOIC_BIND
    for k in ("STOIC_BIND", "STOIC_WORKERS", "STOIC_TIMEOUT"):
        os.environ.pop(k, None)

    spec = importlib.util.spec_from_file_location(
        "gunicorn_conf_default_under_test",
        "gunicorn.conf.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.bind == "127.0.0.1:5001", (
        f"Default bind must be loopback for safety; got {module.bind}"
    )
