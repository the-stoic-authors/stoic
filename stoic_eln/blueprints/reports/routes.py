"""Routes for the /reports blueprint."""

from __future__ import annotations

from datetime import date

from flask import render_template, request
from flask_login import login_required

from stoic_eln.blueprints.reports import bp
from stoic_eln.extensions import db
from stoic_eln.models import Substance
from stoic_eln.services.spending_report import compute_spending
from stoic_eln.services.substance_report import (
    compute_substance_report,
    render_cost_sparkline_svg,
)


def _parse_date(raw: str | None) -> date | None:
    """Tolerant ISO-date parser. Empty / unparseable → None."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except (TypeError, ValueError):
        return None


def _resolve_period(
    preset: str | None,
    raw_from: str | None,
    raw_to: str | None,
) -> tuple[date, date, str]:
    """Resolve the reporting window from a preset or custom range.

    Presets: '3m', '6m', '12m' (months back from today). 'custom'
    uses the explicit from/to. Anything else defaults to 12 months.
    Returns (date_from, date_to, normalized_preset).
    """
    from datetime import timedelta

    today = date.today()
    if preset == "custom":
        d_from = _parse_date(raw_from) or (today - timedelta(days=365))
        d_to = _parse_date(raw_to) or today
        return d_from, d_to, "custom"

    months = {"3m": 90, "6m": 180, "12m": 365}
    if preset not in months:
        preset = "12m"
    return today - timedelta(days=months[preset]), today, preset


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


@bp.route("/substance")
@bp.route("/substance/<int:substance_id>")
@login_required
def substance(substance_id: int | None = None):
    """Per-substance report: consumption, stock coverage, cost trend.

    Query params:
        period: '3m' | '6m' | '12m' | 'custom' (default: 12m)
        from / to: ISO dates, used when period=custom

    If no substance_id is given, renders the page with a picker and
    no report body (the global "Reports → Substance" entry point).
    When a substance_id is supplied (e.g. from the substance detail
    page), the report is computed and shown.
    """
    period = request.args.get("period", "12m")
    date_from, date_to, period = _resolve_period(
        period,
        request.args.get("from"),
        request.args.get("to"),
    )

    # All substances for the picker dropdown
    from sqlalchemy import func as _func

    substances = (
        db.session.query(Substance)
        .filter(Substance.is_active.is_(True))
        .order_by(_func.lower(Substance.name).asc())
        .all()
    )

    report = None
    cost_svg = ""
    if substance_id is not None:
        report = compute_substance_report(
            substance_id,
            date_from=date_from,
            date_to=date_to,
        )
        if report is not None:
            cost_svg = render_cost_sparkline_svg(report.cost_trend.points)

    return render_template(
        "reports/substance.html",
        report=report,
        substances=substances,
        selected_id=substance_id,
        period=period,
        date_from=date_from,
        date_to=date_to,
        cost_svg=cost_svg,
    )
