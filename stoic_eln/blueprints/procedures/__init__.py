"""Procedures blueprint: lab-global library of reusable workup steps.

See models/step_template.py for the data shape and the copy-not-
reference design rationale.
"""

from flask import Blueprint

bp = Blueprint("procedures", __name__, url_prefix="/procedures")

from stoic_eln.blueprints.procedures import routes  # noqa: E402,F401
