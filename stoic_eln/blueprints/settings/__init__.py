"""Settings blueprint — admin-only configuration UI."""

from flask import Blueprint

bp = Blueprint(
    "settings",
    __name__,
    url_prefix="/settings",
    template_folder="../../templates/settings",
)

from stoic_eln.blueprints.settings import routes  # noqa: E402, F401
