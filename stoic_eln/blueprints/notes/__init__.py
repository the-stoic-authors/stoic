"""Notes blueprint (Settimana 6 patch 9)."""

from flask import Blueprint

bp = Blueprint("notes", __name__, url_prefix="/notes")

from stoic_eln.blueprints.notes import routes  # noqa: F401, E402
