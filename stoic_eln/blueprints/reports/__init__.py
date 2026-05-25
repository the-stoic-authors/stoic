"""Reports blueprint: spending, cost analysis, future financial views.

Hosted at /reports. First report (Settimana 7 patch 14.6.8) is
the spending overview: how much money flowed into reagent
purchases over a chosen period, bucketed week / month / quarter
/ year. Future expansions: cost-per-mixture breakdowns,
reagent-usage frequency, group-level budget tracking.
"""

from flask import Blueprint

bp = Blueprint(
    "reports",
    __name__,
    template_folder="../../templates/reports",
    url_prefix="/reports",
)

from stoic_eln.blueprints.reports import routes  # noqa: E402, F401
