from flask import Blueprint

bp = Blueprint("suppliers", __name__, url_prefix="/suppliers")

from stoic_eln.blueprints.suppliers import routes  # noqa: E402, F401
