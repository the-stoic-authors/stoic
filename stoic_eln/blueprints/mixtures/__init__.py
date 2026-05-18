"""Mixtures blueprint: list, detail, create, edit prepared lab solutions.

Counterpart to ``substances`` for ``Mixture`` entities — physical
preparations like HCl 1N, eluents, buffers. See models/mixture.py for
the data shape.
"""

from flask import Blueprint

bp = Blueprint(
    "mixtures",
    __name__,
    url_prefix="/mixtures",
    template_folder="../../templates/mixtures",
)

from stoic_eln.blueprints.mixtures import routes  # noqa: E402, F401
