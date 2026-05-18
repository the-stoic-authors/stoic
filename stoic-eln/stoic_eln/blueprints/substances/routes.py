"""Stoic ELN — Substance routes."""

from __future__ import annotations

import logging

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import or_

from stoic_eln.blueprints.substances import bp
from stoic_eln.blueprints.substances.forms import (
    PubChemConfirmForm,
    PubChemImportForm,
    SubstanceForm,
)
from stoic_eln.extensions import db
from stoic_eln.models.hazard_phrase import HazardPhrase
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.substance import Substance
from stoic_eln.services import pubchem
from stoic_eln.services.audit import log_event

logger = logging.getLogger(__name__)


def _parse_phrase_codes(text: str) -> list[str]:
    """Split 'H225, H319, H336' into ['H225', 'H319', 'H336']."""
    if not text:
        return []
    return [c.strip().upper() for c in text.split(",") if c.strip()]


def _phrase_dict(codes: list[str], locale: str) -> list[dict]:
    """Look up phrase texts for ``codes`` in the given ``locale``.

    Returns list of {'code': 'H225', 'text': '...'} entries.
    Codes without a stored translation get an empty text.
    """
    if not codes:
        return []
    rows = (
        db.session.query(HazardPhrase)
        .filter(HazardPhrase.code.in_(codes))
        .all()
    )
    by_code = {r.code: r for r in rows}
    out = []
    for code in codes:
        phrase = by_code.get(code)
        out.append({
            "code": code,
            "text": phrase.text(locale) if phrase else "",
        })
    return out


@bp.route("/")
@login_required
def list_view():
    """List substances with live search.

    Query params:
        q: search string (matches name, IUPAC, CAS, formula, batch_code)
        show_inactive: '1' to also show soft-deleted entries
    """
    q = request.args.get("q", "").strip()
    show_inactive = request.args.get("show_inactive") == "1"

    query = db.session.query(Substance)

    if not show_inactive:
        query = query.filter(Substance.is_active.is_(True))

    if q:
        like = f"%{q}%"
        # Search across substance fields + batch codes of related inventory items
        from sqlalchemy.orm import aliased

        inv = aliased(InventoryItem)
        query = (
            query.outerjoin(inv, inv.substance_id == Substance.id)
            .filter(
                or_(
                    Substance.name.ilike(like),
                    Substance.iupac_name.ilike(like),
                    Substance.cas_number.ilike(like),
                    Substance.molecular_formula.ilike(like),
                    Substance.inchi_key.ilike(like),
                    inv.batch_code.ilike(like),
                )
            )
            .distinct()
        )

    query = query.order_by(Substance.name.asc())
    substances = query.all()

    # HTMX partial: return only the table fragment
    if request.headers.get("HX-Request"):
        return render_template(
            "substances/_list_table.html",
            substances=substances,
            q=q,
        )

    return render_template(
        "substances/list.html",
        substances=substances,
        q=q,
        show_inactive=show_inactive,
    )


@bp.route("/<int:substance_id>")
@login_required
def detail(substance_id: int):
    sub = db.session.get(Substance, substance_id)
    if sub is None:
        abort(404)

    # Look up phrase texts for the active locale
    from flask_babel import get_locale

    locale = str(get_locale())
    h_phrases = _phrase_dict(sub.h_phrases or [], locale)
    p_phrases = _phrase_dict(sub.p_phrases or [], locale)

    log_event(action="read", entity_type="substance", entity_id=sub.id)

    return render_template(
        "substances/detail.html",
        substance=sub,
        h_phrases=h_phrases,
        p_phrases=p_phrases,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = SubstanceForm()
    if form.validate_on_submit():
        sub = Substance(
            name=form.name.data,
            iupac_name=form.iupac_name.data or None,
            cas_number=form.cas_number.data or None,
            molecular_formula=form.molecular_formula.data or None,
            molecular_weight=form.molecular_weight.data,
            smiles=form.smiles.data or None,
            inchi=form.inchi.data or None,
            inchi_key=(form.inchi_key.data or "").upper() or None,
            density=form.density.data,
            state=form.state.data or None,
            is_solvent=form.is_solvent.data,
            melting_point_c=form.melting_point_c.data,
            boiling_point_c=form.boiling_point_c.data,
            notes=form.notes.data or None,
            ghs_pictograms=list(form.ghs_pictograms.data) or [],
            h_phrases=_parse_phrase_codes(form.h_phrases_text.data),
            p_phrases=_parse_phrase_codes(form.p_phrases_text.data),
            created_by_id=current_user.id,
        )

        # Detect duplicate by InChIKey
        if sub.inchi_key:
            existing = (
                db.session.query(Substance)
                .filter_by(inchi_key=sub.inchi_key)
                .first()
            )
            if existing:
                flash(
                    _("Esiste già una sostanza con questo InChIKey: %(name)s",
                      name=existing.display_name),
                    "warning",
                )
                return redirect(url_for("substances.detail", substance_id=existing.id))

        db.session.add(sub)
        db.session.commit()
        log_event(action="create", entity_type="substance", entity_id=sub.id)
        flash(_("Sostanza '%(name)s' creata.", name=sub.name), "success")
        return redirect(url_for("substances.detail", substance_id=sub.id))

    return render_template("substances/form.html", form=form, substance=None)


@bp.route("/<int:substance_id>/edit", methods=["GET", "POST"])
@login_required
def edit(substance_id: int):
    sub = db.session.get(Substance, substance_id)
    if sub is None:
        abort(404)

    form = SubstanceForm(obj=sub)
    # On GET, populate the phrase text fields from the JSON columns
    if request.method == "GET":
        form.h_phrases_text.data = ", ".join(sub.h_phrases or [])
        form.p_phrases_text.data = ", ".join(sub.p_phrases or [])
        form.ghs_pictograms.data = sub.ghs_pictograms or []

    if form.validate_on_submit():
        sub.name = form.name.data
        sub.iupac_name = form.iupac_name.data or None
        sub.cas_number = form.cas_number.data or None
        sub.molecular_formula = form.molecular_formula.data or None
        sub.molecular_weight = form.molecular_weight.data
        sub.smiles = form.smiles.data or None
        sub.inchi = form.inchi.data or None
        new_key = (form.inchi_key.data or "").upper() or None
        # Prevent collision with another substance
        if new_key and new_key != sub.inchi_key:
            other = (
                db.session.query(Substance)
                .filter(Substance.inchi_key == new_key, Substance.id != sub.id)
                .first()
            )
            if other:
                flash(
                    _("InChIKey già usato dalla sostanza '%(name)s'", name=other.display_name),
                    "danger",
                )
                return render_template("substances/form.html", form=form, substance=sub)
        sub.inchi_key = new_key
        sub.density = form.density.data
        sub.state = form.state.data or None
        sub.is_solvent = form.is_solvent.data
        sub.melting_point_c = form.melting_point_c.data
        sub.boiling_point_c = form.boiling_point_c.data
        sub.notes = form.notes.data or None
        sub.ghs_pictograms = list(form.ghs_pictograms.data) or []
        sub.h_phrases = _parse_phrase_codes(form.h_phrases_text.data)
        sub.p_phrases = _parse_phrase_codes(form.p_phrases_text.data)

        db.session.commit()
        log_event(action="update", entity_type="substance", entity_id=sub.id)
        flash(_("Sostanza '%(name)s' aggiornata.", name=sub.name), "success")
        return redirect(url_for("substances.detail", substance_id=sub.id))

    return render_template("substances/form.html", form=form, substance=sub)


@bp.route("/<int:substance_id>/deactivate", methods=["POST"])
@login_required
def deactivate(substance_id: int):
    sub = db.session.get(Substance, substance_id)
    if sub is None:
        abort(404)
    sub.is_active = False
    db.session.commit()
    log_event(action="deactivate", entity_type="substance", entity_id=sub.id)
    flash(_("Sostanza '%(name)s' disattivata.", name=sub.name), "info")
    return redirect(url_for("substances.list_view"))


@bp.route("/<int:substance_id>/reactivate", methods=["POST"])
@login_required
def reactivate(substance_id: int):
    sub = db.session.get(Substance, substance_id)
    if sub is None:
        abort(404)
    sub.is_active = True
    db.session.commit()
    log_event(action="reactivate", entity_type="substance", entity_id=sub.id)
    flash(_("Sostanza '%(name)s' riattivata.", name=sub.name), "info")
    return redirect(url_for("substances.detail", substance_id=sub.id))


@bp.route("/<int:substance_id>/sds")
@login_required
def sds(substance_id: int):
    """Print-friendly safety data sheet."""
    sub = db.session.get(Substance, substance_id)
    if sub is None:
        abort(404)

    from datetime import date

    from flask_babel import get_locale

    locale = str(get_locale())
    h_phrases = _phrase_dict(sub.h_phrases or [], locale)
    p_phrases = _phrase_dict(sub.p_phrases or [], locale)

    log_event(action="export_sds", entity_type="substance", entity_id=sub.id)

    return render_template(
        "substances/sds.html",
        substance=sub,
        h_phrases=h_phrases,
        p_phrases=p_phrases,
        now_iso=date.today().isoformat(),
    )


# ─── PubChem import workflow ─────────────────────────────────────────────────


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_pubchem():
    """Step 1 of PubChem import: search."""
    form = PubChemImportForm()
    error = None

    if form.validate_on_submit():
        query = form.query.data.strip()
        qtype = form.query_type.data
        if qtype == "auto":
            qtype = None

        try:
            result = pubchem.search(query, query_type=qtype)
        except pubchem.PubChemNotFound:
            error = _("Nessun risultato trovato per '%(q)s'.", q=query)
        except pubchem.PubChemError as e:
            error = _("Errore PubChem: %(err)s", err=str(e))
            logger.exception("PubChem search failed")
        else:
            # Check for duplicate before showing preview
            existing = None
            if result.inchi_key:
                existing = (
                    db.session.query(Substance)
                    .filter_by(inchi_key=result.inchi_key)
                    .first()
                )

            # Stash result in session for confirmation step
            session["pubchem_result"] = {
                "cid": result.cid,
                "name": result.name,
                "iupac_name": result.iupac_name,
                "cas_number": result.cas_number,
                "molecular_formula": result.molecular_formula,
                "molecular_weight": result.molecular_weight,
                "smiles": result.smiles,
                "inchi": result.inchi,
                "inchi_key": result.inchi_key,
                "density": result.density,
                "state": result.state,
                "melting_point_c": result.melting_point_c,
                "boiling_point_c": result.boiling_point_c,
                "ghs_pictograms": result.ghs_pictograms,
                "h_phrases": result.h_phrases,
                "p_phrases": result.p_phrases,
            }

            from flask_babel import get_locale

            locale = str(get_locale())
            return render_template(
                "substances/import_preview.html",
                result=result,
                existing=existing,
                h_phrases=_phrase_dict(result.h_phrases, locale),
                p_phrases=_phrase_dict(result.p_phrases, locale),
                confirm_form=PubChemConfirmForm(),
            )

    return render_template("substances/import_search.html", form=form, error=error)


@bp.route("/import/confirm", methods=["POST"])
@login_required
def import_confirm():
    """Step 2: actually save the PubChem result as a Substance."""
    form = PubChemConfirmForm()
    if not form.validate_on_submit():
        flash(_("Token CSRF mancante. Riprova."), "danger")
        return redirect(url_for("substances.import_pubchem"))

    data = session.pop("pubchem_result", None)
    if not data:
        flash(_("Sessione scaduta. Cerca di nuovo."), "warning")
        return redirect(url_for("substances.import_pubchem"))

    inchi_key = data.get("inchi_key")
    if inchi_key:
        existing = (
            db.session.query(Substance).filter_by(inchi_key=inchi_key).first()
        )
        if existing:
            flash(
                _("Sostanza già presente: '%(name)s'", name=existing.display_name),
                "info",
            )
            return redirect(url_for("substances.detail", substance_id=existing.id))

    sub = Substance(
        name=data.get("name") or data.get("iupac_name") or f"CID {data['cid']}",
        iupac_name=data.get("iupac_name"),
        cas_number=data.get("cas_number"),
        molecular_formula=data.get("molecular_formula"),
        molecular_weight=data.get("molecular_weight"),
        smiles=data.get("smiles"),
        inchi=data.get("inchi"),
        inchi_key=inchi_key,
        density=data.get("density"),
        state=data.get("state"),
        is_solvent=False,  # admin can flip this in edit
        melting_point_c=data.get("melting_point_c"),
        boiling_point_c=data.get("boiling_point_c"),
        ghs_pictograms=data.get("ghs_pictograms") or [],
        h_phrases=data.get("h_phrases") or [],
        p_phrases=data.get("p_phrases") or [],
        pubchem_cid=data.get("cid"),
        created_by_id=current_user.id,
    )
    db.session.add(sub)
    db.session.commit()
    log_event(
        action="create",
        entity_type="substance",
        entity_id=sub.id,
        details={"source": "pubchem", "cid": sub.pubchem_cid},
    )
    flash(
        _("Importata da PubChem: '%(name)s'", name=sub.name),
        "success",
    )
    return redirect(url_for("substances.detail", substance_id=sub.id))
