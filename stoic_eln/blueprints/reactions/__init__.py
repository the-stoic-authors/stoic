"""Reactions blueprint: list, detail, create, edit, components."""

from flask import Blueprint

bp = Blueprint(
    "reactions",
    __name__,
    url_prefix="/reactions",
    template_folder="../../templates/reactions",
)

from stoic_eln.blueprints.reactions import routes  # noqa: E402, F401
