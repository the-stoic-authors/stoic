"""Stoic ELN — Gunicorn configuration.

Reads operational settings from environment variables so the same
file works for tiny single-CPU Pi installs and beefier servers
without forking config:

    STOIC_BIND      default 127.0.0.1:5001
                    Set to "0.0.0.0:5001" to expose on the LAN
                    (consider running Caddy/nginx in front instead).
    STOIC_WORKERS   default 2
                    Rule of thumb: (2 * CPU_CORES) + 1.
                    On a Pi 3B with 1 GB RAM, drop to 1.
    STOIC_TIMEOUT   default 120 (seconds)
                    PDF generation occasionally takes longer than
                    the gunicorn default of 30 s.
    STOIC_LOGLEVEL  default info

Usage:

    gunicorn -c gunicorn.conf.py wsgi:app

The ``when_ready`` hook starts the in-process background scheduler
(nightly backup, etc.) in the master process. Gunicorn forks workers
from the master, but BackgroundScheduler runs in a thread and threads
are NOT inherited by fork() — so the scheduler exists exactly once,
in the master, which is what we want. The worker processes serve
HTTP requests via ``wsgi.app``, which calls ``create_app`` with
``start_scheduler=False``.

Why a separate config file rather than command-line flags: this is
the file the operator edits when they want different settings for
their lab. Putting it in version control means upgrades don't blow
away their tuning.
"""

from __future__ import annotations

import os

# ── Bind & workers ────────────────────────────────────────────────

bind = os.environ.get("STOIC_BIND", "127.0.0.1:5001")
workers = int(os.environ.get("STOIC_WORKERS", "2"))
timeout = int(os.environ.get("STOIC_TIMEOUT", "120"))

# ── Logging ───────────────────────────────────────────────────────

# "-" means stdout/stderr — systemd captures it via the unit's
# StandardOutput/StandardError directives (typically journal).
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("STOIC_LOGLEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)ss'

# ── Worker class ──────────────────────────────────────────────────

# Sync workers are fine for Stoic: requests are short, no
# long-polling, no websockets. If we ever add server-sent events,
# revisit with gevent or uvloop workers.
worker_class = "sync"

# ── Process management ────────────────────────────────────────────

# Recycle workers periodically to bound memory growth from accidental
# leaks (RDKit, ReportLab — both have been known to retain refs).
max_requests = 1000
max_requests_jitter = 50

# ── Master process: scheduler home ────────────────────────────────

# Keep a module-level reference to the scheduler app so it isn't
# garbage-collected after when_ready returns.
_scheduler_app = None


def when_ready(server):
    """Start the in-process scheduler in the master process.

    Runs exactly once, just after gunicorn finishes booting and
    workers are forked. The scheduler thread lives in the master;
    workers are not affected (they don't inherit threads from
    fork()).

    If APScheduler isn't installed (optional dep), this is logged
    by ``init_scheduler`` and the rest of the system keeps working
    — manual ``stoic backup`` from the CLI still functions.
    """
    global _scheduler_app

    server.log.info("Stoic: starting background scheduler in master")
    from stoic_eln import create_app

    _scheduler_app = create_app(start_scheduler=True)
    server.log.info("Stoic: scheduler ready")
