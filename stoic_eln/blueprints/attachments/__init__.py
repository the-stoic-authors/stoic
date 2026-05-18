"""Attachments blueprint (Settimana 6 patch 10)."""
from flask import Blueprint

bp = Blueprint("attachments", __name__, url_prefix="/attachments")

from stoic_eln.blueprints.attachments import routes  # noqa: F401, E402
