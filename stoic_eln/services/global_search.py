"""Global search across the main domain entities.

Powers the Cmd-K command palette. Each entity contributes a small set of
searchable text columns; results are returned as lightweight dicts ready
for JSON serialisation (no ORM objects leak to the template/JS layer).

Design notes:
- SQLite ``LIKE`` is case-insensitive for ASCII, which is what we need for
  codes, CAS numbers, formulae and Latin names. We match a single ``%q%``
  substring per column.
- Reactions: only ``published`` ones are searchable. Drafts are personal
  work-in-progress and would just be noise in a global palette.
- Inactive / archived rows are excluded everywhere.
- Each entity is capped independently so one type can't crowd out the
  others; the caller can apply a global cap too.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import or_, select

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.mixture import Mixture
from stoic_eln.models.mixture_prep import MixturePrep
from stoic_eln.models.order import Order
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.run import Run
from stoic_eln.models.step_template import StepTemplate
from stoic_eln.models.substance import Substance

# Per-entity result cap.
PER_TYPE_LIMIT = 6


@dataclass
class SearchHit:
    """One search result, ready for JSON."""

    type: str  # entity kind, e.g. "substance"
    type_label: str  # human label, already translated by the caller
    id: int
    title: str  # primary line
    subtitle: str | None  # secondary line (context)
    url: str  # detail page


def _like(column, q: str):
    return column.ilike(f"%{q}%")


def search(query: str, limit_per_type: int = PER_TYPE_LIMIT) -> list[dict]:
    """Run the global search and return a flat list of result dicts.

    The ``url`` field is left empty here and filled in by the blueprint,
    which has access to ``url_for``. Keeping URL building out of the
    service keeps it importable and unit-testable without an app context
    for routing.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []

    hits: list[SearchHit] = []

    # ── Substances ──────────────────────────────────────────────────────
    stmt = (
        select(Substance)
        .where(
            Substance.is_active.is_(True),
            or_(
                _like(Substance.name, q),
                _like(Substance.iupac_name, q),
                _like(Substance.cas_number, q),
                _like(Substance.molecular_formula, q),
            ),
        )
        .limit(limit_per_type)
    )
    for s in db.session.scalars(stmt):
        subtitle_bits = [b for b in (s.cas_number, s.molecular_formula) if b]
        hits.append(
            SearchHit(
                type="substance",
                type_label="",
                id=s.id,
                title=s.name,
                subtitle=" · ".join(subtitle_bits) or None,
                url="",
            )
        )

    # ── Reactions (published only) ──────────────────────────────────────
    stmt = (
        select(Reaction)
        .where(
            Reaction.is_active.is_(True),
            Reaction.status == "published",
            Reaction.is_archived.is_(False),
            or_(
                _like(Reaction.code, q),
                _like(Reaction.title, q),
                _like(Reaction.template_code, q),
            ),
        )
        .limit(limit_per_type)
    )
    for r in db.session.scalars(stmt):
        hits.append(
            SearchHit(
                type="reaction",
                type_label="",
                id=r.id,
                title=r.title,
                subtitle=r.code,
                url="",
            )
        )

    # ── Runs ────────────────────────────────────────────────────────────
    stmt = (
        select(Run)
        .where(
            or_(
                _like(Run.code, q),
                _like(Run.operator_code, q),
                _like(Run.template_code, q),
                _like(Run.template_title_snapshot, q),
            ),
        )
        .limit(limit_per_type)
    )
    for run in db.session.scalars(stmt):
        subtitle_bits = [b for b in (run.template_title_snapshot, run.status) if b]
        hits.append(
            SearchHit(
                type="run",
                type_label="",
                id=run.id,
                title=run.code,
                subtitle=" · ".join(subtitle_bits) or None,
                url="",
            )
        )

    # ── Mixtures ────────────────────────────────────────────────────────
    stmt = (
        select(Mixture)
        .where(
            Mixture.is_active.is_(True),
            or_(
                _like(Mixture.name, q),
                _like(Mixture.description, q),
            ),
        )
        .limit(limit_per_type)
    )
    for m in db.session.scalars(stmt):
        hits.append(
            SearchHit(
                type="mixture",
                type_label="",
                id=m.id,
                title=m.name,
                subtitle=m.description[:80] if m.description else None,
                url="",
            )
        )

    # ── Inventory items ─────────────────────────────────────────────────
    stmt = (
        select(InventoryItem)
        .where(
            InventoryItem.is_active.is_(True),
            or_(
                _like(InventoryItem.batch_code, q),
                _like(InventoryItem.supplier, q),
                _like(InventoryItem.catalogue_number, q),
                _like(InventoryItem.location, q),
            ),
        )
        .limit(limit_per_type)
    )
    for it in db.session.scalars(stmt):
        owner = it.substance.name if it.substance else (it.mixture.name if it.mixture else None)
        subtitle_bits = [b for b in (owner, it.batch_code, it.location) if b]
        hits.append(
            SearchHit(
                type="inventory",
                type_label="",
                id=it.id,
                title=owner or (it.batch_code or f"#{it.id}"),
                subtitle=" · ".join(subtitle_bits) or None,
                url="",
            )
        )

    # ── Orders ──────────────────────────────────────────────────────────
    stmt = (
        select(Order)
        .where(
            or_(
                _like(Order.supplier, q),
                _like(Order.catalogue_number, q),
                _like(Order.internal_order_ref, q),
            ),
        )
        .limit(limit_per_type)
    )
    for o in db.session.scalars(stmt):
        owner = o.substance.name if o.substance else (o.mixture.name if o.mixture else None)
        subtitle_bits = [b for b in (owner, o.supplier, o.status) if b]
        hits.append(
            SearchHit(
                type="order",
                type_label="",
                id=o.id,
                title=owner or (o.internal_order_ref or f"#{o.id}"),
                subtitle=" · ".join(subtitle_bits) or None,
                url="",
            )
        )

    # ── Mixture preparations ────────────────────────────────────────────
    stmt = (
        select(MixturePrep)
        .where(
            _like(MixturePrep.code, q),
        )
        .limit(limit_per_type)
    )
    for p in db.session.scalars(stmt):
        owner = p.mixture.name if p.mixture else None
        hits.append(
            SearchHit(
                type="prep",
                type_label="",
                id=p.id,
                title=p.code,
                subtitle=owner,
                url="",
            )
        )

    # ── Procedures (step templates) ─────────────────────────────────────
    stmt = (
        select(StepTemplate)
        .where(
            or_(
                _like(StepTemplate.name, q),
                _like(StepTemplate.description, q),
            ),
        )
        .limit(limit_per_type)
    )
    for t in db.session.scalars(stmt):
        hits.append(
            SearchHit(
                type="procedure",
                type_label="",
                id=t.id,
                title=t.name,
                subtitle=t.description[:80] if t.description else None,
                url="",
            )
        )

    return [asdict(h) for h in hits]
