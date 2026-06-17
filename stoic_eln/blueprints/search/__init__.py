"""Global search blueprint — powers the Cmd-K command palette."""

from flask import Blueprint

bp = Blueprint("search", __name__, url_prefix="/search")

from stoic_eln.blueprints.search import routes  # noqa: E402,F401
