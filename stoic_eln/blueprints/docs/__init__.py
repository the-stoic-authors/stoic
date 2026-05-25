"""Stoic — in-app documentation blueprint (Settimana 6 patch 14.6).

Serves the manuals shipped in ``docs/{it,en}/*.md`` as HTML
rendered at request time. Three pages:

* ``user-manual`` — accessible to all logged-in users
* ``admin-manual`` — admin only
* ``developer-manual`` — admin only (sysadmin / contributor doc)

Each page picks IT or EN based on ``current_user.locale``.
"""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    "docs",
    __name__,
    url_prefix="/docs",
    template_folder="../../templates/docs",
)

from stoic_eln.blueprints.docs import routes  # noqa: E402, F401
