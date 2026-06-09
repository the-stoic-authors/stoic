"""Stoic ELN — WSGI entrypoint for production servers.

Gunicorn, uWSGI, mod_wsgi, and any other WSGI-compliant server
imports ``app`` from this module to run Stoic in production:

    gunicorn -c gunicorn.conf.py wsgi:app

The factory ``create_app()`` is invoked with ``start_scheduler=False``
because the in-process scheduler (nightly backups, etc.) must run
in exactly ONE process. In a multi-worker setup, each worker is a
separate Python process; if every worker started its own scheduler
the nightly backup would fire N times. We delegate scheduler
startup to gunicorn's ``when_ready`` hook in ``gunicorn.conf.py``,
which runs once in the master process.

Configuration is read from environment variables via
``stoic_eln.config.ProductionConfig`` (or whichever class
``FLASK_ENV`` resolves to). At minimum, set ``SECRET_KEY`` and,
if running outside the default location, ``DATABASE_URL``.

For development on a single machine, prefer ``flask run`` (or
``make run``) — that path goes through ``create_app()`` with the
default ``start_scheduler=True``, so the backup scheduler runs as
expected without any extra setup.
"""

from __future__ import annotations

from stoic_eln import create_app

app = create_app(start_scheduler=False)
