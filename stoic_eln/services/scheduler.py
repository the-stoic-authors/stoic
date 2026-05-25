"""Stoic ELN — Background scheduler (APScheduler integration).

Runs in-process. Currently used only for the nightly backup job,
but a single scheduler can grow more jobs later (e.g. inventory
expiry alerts, prep-stock reminders).

Design constraints:

- **Single instance**: Flask's reloader spawns two processes in
  debug mode. We attach to ``app.extensions["scheduler"]`` so the
  child process doesn't double-register the job.
- **App context for jobs**: APScheduler runs jobs in worker
  threads with no Flask context. The job wrapper pushes one.
- **Live config**: the job re-reads settings from AppSetting at
  every fire, so the user can change the backup hour from the UI
  without restarting. (We do not, however, re-schedule the job
  itself dynamically — that requires a service restart. Minor UX
  trade-off, documented in the settings UI.)
- **Failures are non-fatal**: ``run_scheduled_backup`` swallows
  exceptions and logs them, so a broken backup never takes down
  the scheduler.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)


def init_scheduler(app: Flask) -> None:
    """Initialise the background scheduler. Idempotent and a no-op
    in TESTING mode or when ``BACKUP_SCHEDULER_DISABLED`` is set."""
    if app.config.get("TESTING"):
        return
    if app.config.get("BACKUP_SCHEDULER_DISABLED"):
        return
    if "scheduler" in app.extensions:
        return  # Reloader's child process; first init already happened.

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        # APScheduler not installed: log and continue. The CLI
        # ``flask backup run`` still works without it.
        logger.warning(
            "APScheduler not installed; scheduled backups disabled. "
            "Install with: pip install APScheduler"
        )
        return

    # Read initial schedule from AppSetting. If the DB isn't ready
    # yet (very first run before init-db), fall back to 03:00.
    hour, minute = 3, 0
    try:
        with app.app_context():
            from stoic_eln.services.backup import get_settings

            s = get_settings()
            hour, minute = s["hour"], s["minute"]
    except Exception as e:
        logger.warning("backup settings unreadable on startup: %s", e)

    scheduler = BackgroundScheduler(timezone="UTC")

    def _wrapped():
        # APScheduler workers have no Flask context. Push one and
        # delegate to the service-level function.
        with app.app_context():
            from stoic_eln.services.backup import run_scheduled_backup

            run_scheduled_backup()

    scheduler.add_job(
        _wrapped,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="nightly_backup",
        name="Nightly DB backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,  # if missed (e.g. machine asleep), run once on wake
    )

    scheduler.start()
    app.extensions["scheduler"] = scheduler
    logger.info(
        "scheduler started: nightly backup at %02d:%02d UTC",
        hour,
        minute,
    )

    # Stop the scheduler cleanly on app teardown. Critical for
    # tests and for the reloader, which would otherwise leak
    # threads.
    import atexit

    atexit.register(lambda: scheduler.shutdown(wait=False))
