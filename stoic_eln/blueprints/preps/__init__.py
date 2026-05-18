"""Preps blueprint: read-only history of mixture preparations.

Mixture preparations are written by ``mixtures.execute_prep``; this
blueprint provides the list / detail views to audit and reference
them. Preparations are immutable — once committed, they can be
viewed but not edited or deleted (the corresponding output
``InventoryItem`` can be deactivated through inventory's own UI if
needed).
"""

from flask import Blueprint

bp = Blueprint(
    "preps",
    __name__,
    url_prefix="/preps",
    template_folder="../../templates/preps",
)

from stoic_eln.blueprints.preps import routes  # noqa: E402, F401
