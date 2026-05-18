"""Stoic ELN — Runs blueprint."""

from flask import Blueprint

bp = Blueprint("runs", __name__, url_prefix="/runs")

from stoic_eln.blueprints.runs import routes  # noqa: E402, F401
