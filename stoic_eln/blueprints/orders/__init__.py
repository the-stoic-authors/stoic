"""Orders blueprint: planned/in-progress purchases (Settimana 6 patch 3)."""

from flask import Blueprint

bp = Blueprint(
    "orders",
    __name__,
    url_prefix="/orders",
    template_folder="../../templates/orders",
)

from stoic_eln.blueprints.orders import routes  # noqa: E402, F401
