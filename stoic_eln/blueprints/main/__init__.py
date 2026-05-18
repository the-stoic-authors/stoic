"""Main blueprint: landing/dashboard."""

from flask import Blueprint

bp = Blueprint("main", __name__, template_folder="../../templates/main")

from stoic_eln.blueprints.main import routes  # noqa: E402, F401
