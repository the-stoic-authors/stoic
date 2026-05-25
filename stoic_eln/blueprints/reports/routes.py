"""Routes for the /reports blueprint."""

from __future__ import annotations

from datetime import date

from flask import render_template, request
from flask_login import login_required

from stoic_eln.blueprints.reports import bp
from stoic_eln.services.spending_report import compute_spending


def _parse_date(raw: str | None) -> date | None:
    """Tolerant ISO-date parser. Empty / unparseable → None."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except (TypeError, ValueError):
        return None


@bp.route("/")
@login_required
def index():
    """Reports landing page — links to the available reports.

    Right now it only links to /reports/spending, but the
    landing pattern is in place for the next reports (cost
    breakdowns, group budgets, etc.) without needing to add
    new top-level nav entries.
    """
    return render_template("reports/index.html")


@bp.route("/spending")
@login_required
def spending():
    """Spending overview: purchase costs bucketed by week / month
    / quarter / year, with optional date-range filter.

    Query params:
        bucket: 'week' | 'month' | 'quarter' | 'year' (default: month)
        from: ISO date (YYYY-MM-DD), inclusive
        to:   ISO date (YYYY-MM-DD), inclusive

    Result: ``SpendingReport`` with rows sorted newest-first.
    """
    bucket = request.args.get("bucket", "month")
    if bucket not in ("week", "month", "quarter", "year"):
        bucket = "month"
    date_from = _parse_date(request.args.get("from"))
    date_to = _parse_date(request.args.get("to"))

    report = compute_spending(
        bucket=bucket,
        date_from=date_from,
        date_to=date_to,
    )

    return render_template(
        "reports/spending.html",
        report=report,
        bucket=bucket,
        date_from=date_from,
        date_to=date_to,
    )
