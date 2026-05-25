"""Stoic ELN — Preparation history routes.

Read-only. List + detail. Filtering by mixture and date range.
"""

from __future__ import annotations


from flask import abort, render_template, request
from flask_login import login_required
from sqlalchemy import desc, func, or_

from stoic_eln.blueprints.preps import bp
from stoic_eln.extensions import db
from stoic_eln.models.mixture import Mixture
from stoic_eln.models.mixture_prep import MixturePrep
from stoic_eln.services.audit import log_event


@bp.route("/")
@login_required
def list_view():
    """List all preparations, most recent first.

    Supports filtering by:
      * ``q`` — text match on code or mixture name
      * ``mixture_id`` — preparations of a specific mixture
      * ``year`` — calendar year of the preparation

    HTMX returns the table fragment; full request renders the page.
    """
    q = (request.args.get("q") or "").strip()
    mixture_id_raw = (request.args.get("mixture_id") or "").strip()
    year_raw = (request.args.get("year") or "").strip()

    query = (
        db.session.query(MixturePrep)
        .join(Mixture, Mixture.id == MixturePrep.mixture_id)
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                MixturePrep.code.ilike(like),
                Mixture.name.ilike(like),
            )
        )

    try:
        mixture_id = int(mixture_id_raw) if mixture_id_raw else None
    except ValueError:
        mixture_id = None
    if mixture_id:
        query = query.filter(MixturePrep.mixture_id == mixture_id)

    try:
        year = int(year_raw) if year_raw else None
    except ValueError:
        year = None
    if year:
        query = query.filter(MixturePrep.year == year)

    preps = query.order_by(desc(MixturePrep.prepared_at)).limit(500).all()

    # Surface a few stat dropdowns
    years = [
        r[0] for r in (
            db.session.query(MixturePrep.year)
            .distinct()
            .order_by(desc(MixturePrep.year))
            .all()
        )
    ]
    # Only mixtures that have at least one preparation
    mixtures = (
        db.session.query(Mixture)
        .join(MixturePrep, MixturePrep.mixture_id == Mixture.id)
        .distinct()
        .order_by(func.lower(Mixture.name))
        .all()
    )

    if request.headers.get("HX-Request"):
        return render_template(
            "preps/_list_table.html", preps=preps, q=q,
        )

    return render_template(
        "preps/list.html",
        preps=preps, q=q,
        years=years, mixtures=mixtures,
        selected_mixture_id=mixture_id,
        selected_year=year,
    )


@bp.route("/<int:prep_id>")
@login_required
def detail(prep_id: int):
    """Detail of one preparation: components consumed, output lot,
    operator, timestamp, notes.
    """
    prep = db.session.get(MixturePrep, prep_id)
    if prep is None:
        abort(404)

    log_event(action="read", entity_type="mixture_prep", entity_id=prep.id)

    # Attachments associated with this preparation event (photos of
    # the actual prep, CoA of the produced batch, etc). Mixture-level
    # attachments (the recipe SOP, annotated procedure) live on the
    # parent Mixture and are shown there.
    from stoic_eln.services.attachments import list_attachments
    attachments_for_entity = list_attachments("mixture_prep", prep.id)

    return render_template(
        "preps/detail.html",
        prep=prep,
        attachments_for_entity=attachments_for_entity,
    )
