"""Authentication blueprint: login, logout, password change."""

from flask import Blueprint

bp = Blueprint("auth", __name__, template_folder="../../templates/auth")

from stoic_eln.blueprints.auth import routes  # noqa: E402, F401
