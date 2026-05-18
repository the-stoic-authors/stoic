"""Inventory blueprint: lots/batches CRUD and warehouse view."""

from flask import Blueprint

bp = Blueprint(
    "inventory",
    __name__,
    url_prefix="/inventory",
    template_folder="../../templates/inventory",
)

from stoic_eln.blueprints.inventory import routes  # noqa: E402, F401
