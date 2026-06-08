"""Stoic ELN — Onboarding wizard blueprint.

Multi-step setup wizard shown to admins on first login. Covers
the three settings that are painful to change retroactively:

  - Lab name (shows on PDF reports and audit trail)
  - Currency (all historical costs are stored as numbers in this
    currency; switching later does not convert anything)
  - Run/prep code format (changing it mid-stream makes new runs
    have codes incompatible with older ones)

Other configurations (backup, additional users, ...) live in the
regular Settings pages, not here — those are reversible and can
be done at any time.
"""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")

from stoic_eln.blueprints.onboarding import routes  # noqa: E402, F401
