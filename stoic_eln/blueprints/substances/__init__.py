"""Substances blueprint: list, detail, create, edit, import from PubChem."""

from flask import Blueprint

bp = Blueprint(
    "substances",
    __name__,
    url_prefix="/substances",
    template_folder="../../templates/substances",
)

from stoic_eln.blueprints.substances import routes  # noqa: E402, F401
