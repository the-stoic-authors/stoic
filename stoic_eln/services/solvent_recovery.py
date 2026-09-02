"""Stoic ELN — solvent recovery from run steps (v1.5.0).

What this does
--------------
After a workup or a column, what comes off the rotavap is solvent you
can use again. This service turns that into a real inventory lot, so
the next run can consume it and the lab can see how much fresh solvent
it actually buys.

Recovery is recorded **on the step where it happens**, not at the end of
the run. That is the whole point: the step knows which lots went in, so
the recovered material can carry a composition instead of being an
anonymous volume. What you collect from an EtOAc/hexane column is one
liquid of mixed composition — hence one volume field per step, and a
``Mixture`` lot when more than one component went into it.

Which components went into it is an explicit choice (checkboxes in the
UI), never inferred. An extraction step holds DCM *and* water: you keep
the organic phase and bin the aqueous one. Summing every solvent in the
step would invent a "DCM/water 70:30" lot that exists nowhere, and
since recovered lots get reused, that error would come back in a later
column. Stoic has ``state`` and ``density`` but no miscibility data, so
a rule would be guesswork dressed as automation — and would fail
silently, which is the worst way to fail.

The three rules
---------------
1. **Composition is v/v from the actual quantities** of the ticked
   components, rounded to steps of 10% (``COMPOSITION_STEP_PCT``).
   Rounding is not sloppiness: what condenses in the flask is a running
   average over all the fractions, never an exact ratio. Without
   rounding, dedup would never fire and the catalogue would grow one
   row per column.
2. **One ``Mixture`` per rounded composition**, reused by every later
   recovery that rounds to the same thing. Fifty columns at 90:10 give
   one catalogue row and fifty lots.
3. **Use count follows the worst case** among the ticked components:
   ``max(counts) + 1``. Fresh counts as 0. A volume-weighted average
   would read better but would hide the very thing the counter is for —
   non-volatile impurities accumulate, and topping up with fresh
   solvent dilutes them without removing them. Better wrong by excess.

The reuse constraint (``origin_reaction_id``) lives on the *lot*, not
on the mixture: a mixture is a catalogue entry shared by many lots,
while "may only be reused in this reaction" is a property of the
specific bottle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.mixture import (
    COMPONENT_ROLE_SOLVENT,
    MIXTURE_KIND_ELUENT,
    MIXTURE_KIND_SOLUTION,
    Mixture,
    MixtureComponent,
)
from stoic_eln.models.run_step import RunStep, RunStepComponent

# Composition is rounded to steps of this size before dedup and naming.
# Rico's call (21 August 2026) between 5% and 10%: 10% is closer to how
# a recovered solvent is actually treated at the bench.
COMPOSITION_STEP_PCT = 10.0

_EPS = 1e-9


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RecoveryError(Exception):
    """Raised when a recovery request cannot be honoured."""


@dataclass
class RecoveryShare:
    """One component's contribution to a recovered lot."""

    component: RunStepComponent
    substance_id: int
    volume_mL: float | None = None  # what went IN, when recorded
    raw_percent: float = 0.0  # declared/suggested share, before rounding
    percent: float = 0.0  # rounded v/v share, what ends up in the catalogue
    use_count: int = 0  # of the lot it was drawn from


@dataclass
class RecoveryResult:
    lot: InventoryItem
    mixture: Mixture | None
    shares: list[RecoveryShare] = field(default_factory=list)
    use_count: int = 0
    reused_catalogue_entry: bool = False


# ── candidate components ────────────────────────────────────────────


def _component_volume_mL(sc: RunStepComponent) -> float | None:
    """Volume actually used by this component, in mL.

    Prefers the recorded volume. A component recorded by mass can still
    be converted when its substance carries a density; without one there
    is no honest way to place it in a v/v composition.
    """
    if sc.actual_volume_mL is not None:
        return sc.actual_volume_mL
    if sc.actual_mass_g is not None and sc.substance is not None:
        density = getattr(sc.substance, "density", None)
        if density:
            return sc.actual_mass_g / density
    return None


def recoverable_components(step: RunStep) -> list[RunStepComponent]:
    """Components of ``step`` that could sensibly end up in a recovery.

    Substance-backed, full stop. Free entries (column diameter, ice) and
    mixture-backed components are excluded: the former have no
    substance, the latter would nest a composition inside a
    composition, which the model allows but nobody can read on a label.

    Deliberately *not* filtered on having a recorded quantity. A volume
    is only needed to work out a v/v ratio, so it matters when several
    components feed one recovery and is irrelevant when a single one
    does — recovering from one solvent gives that solvent at 100%
    whatever the numbers say. Filtering here made the whole section
    vanish from steps that were perfectly recoverable (v1.5.0 fix).

    The UI pre-ticks the ones with a solvent role; everything else is
    offered unticked. Deciding is the operator's job.
    """
    return [sc for sc in step.components if sc.substance_id is not None]


def missing_volumes(components: list[RunStepComponent]) -> list[RunStepComponent]:
    """Those of ``components`` with no usable volume.

    Only meaningful for a multi-component recovery, where the ratio
    cannot be computed without them.
    """
    return [sc for sc in components if _component_volume_mL(sc) is None]


def is_default_ticked(sc: RunStepComponent) -> bool:
    """Whether the UI should pre-tick this component."""
    return sc.role == "solvent"


def suggested_percentages(components: list[RunStepComponent]) -> dict[int, float] | None:
    """Composition suggestion from the quantities that went in, or None.

    Only ever a *starting point* for the operator, never the recorded
    truth. What condenses in the flask is not what was loaded onto the
    column: hexane boils at 69 °C and ethyl acetate at 77 °C, so the
    recovered liquid is enriched in the more volatile one. Add a
    gradient, and the habit of concentrating only the fractions that
    carry product, and the real composition can sit well away from the
    charged one.

    Returns None when any component lacks a usable quantity — the UI
    then leaves the fields empty rather than inventing a split.
    """
    if not components:
        return None
    volumes: dict[int, float] = {}
    for sc in components:
        vol = _component_volume_mL(sc)
        if vol is None or vol <= _EPS:
            return None
        volumes[sc.id] = vol
    total = sum(volumes.values())
    if total <= _EPS:
        return None
    return {cid: round(100.0 * v / total, 1) for cid, v in volumes.items()}


# ── composition ─────────────────────────────────────────────────────


def _round_to_step(pct: float) -> float:
    return round(pct / COMPOSITION_STEP_PCT) * COMPOSITION_STEP_PCT


def _rounded_shares(shares: list[RecoveryShare]) -> list[RecoveryShare]:
    """Assign each share a rounded v/v percentage summing to 100.

    Plain rounding does not necessarily add up (33/33/33 → 30/30/30), so
    the largest share absorbs the remainder. A component that rounds to
    zero keeps a nominal 0% and is dropped by the caller: below 5% of
    the volume it does not define the solvent you are holding.
    """
    total = sum(s.raw_percent for s in shares)
    if total <= _EPS:
        raise RecoveryError("La composizione dichiarata è vuota.")

    # Normalise first: the operator types round numbers, and 30/30/30
    # should not be rejected for summing to 90.
    for s in shares:
        s.percent = _round_to_step(100.0 * s.raw_percent / total)

    kept = [s for s in shares if s.percent > _EPS]
    if not kept:
        # Everything rounded away (many tiny, similar components):
        # fall back to the single largest contributor.
        kept = [max(shares, key=lambda s: s.raw_percent)]
        kept[0].percent = 100.0

    drift = 100.0 - sum(s.percent for s in kept)
    if abs(drift) > _EPS:
        biggest = max(kept, key=lambda s: s.raw_percent)
        biggest.percent += drift

    return sorted(kept, key=lambda s: (-s.percent, s.substance_id))


def composition_signature(shares: list[RecoveryShare]) -> str:
    """Stable key for deduplicating catalogue entries.

    Substance ids rather than names, so renaming a substance does not
    fork the catalogue: ``rec:12@60|7@40``.
    """
    parts = [f"{s.substance_id}@{s.percent:g}" for s in shares]
    return "rec:" + "|".join(parts)


def composition_name(shares: list[RecoveryShare]) -> str:
    """Human-facing catalogue name, e.g. ``EtOAc/esano 60:40 (rec.)``."""
    names = "/".join((s.component.substance.name if s.component.substance else "?") for s in shares)
    ratio = ":".join(f"{s.percent:g}" for s in shares)
    return f"{names} {ratio} (rec.)"


# ── the operation ───────────────────────────────────────────────────


def register_recovery(
    step: RunStep,
    component_ids: list[int],
    volume_mL: float,
    *,
    percentages: dict[int, float] | None = None,
    user_id: int | None = None,
    location: str | None = None,
) -> RecoveryResult:
    """Record recovered solvent from ``step`` as a new inventory lot.

    Caller commits. Raises ``RecoveryError`` with a message meant for a
    human when the request does not hold together.
    """
    if volume_mL is None or volume_mL <= _EPS:
        raise RecoveryError("Il volume recuperato deve essere maggiore di zero.")
    if not component_ids:
        raise RecoveryError("Seleziona almeno un componente da cui recuperi il solvente.")

    run = step.run
    candidates = {sc.id: sc for sc in recoverable_components(step)}

    shares: list[RecoveryShare] = []
    for cid in component_ids:
        sc = candidates.get(cid)
        if sc is None:
            raise RecoveryError(
                "Un componente selezionato non appartiene a questo step "
                "o non ha una quantità utilizzabile."
            )
        vol = _component_volume_mL(sc)
        lot = db.session.get(InventoryItem, sc.inventory_item_id) if sc.inventory_item_id else None
        shares.append(
            RecoveryShare(
                component=sc,
                substance_id=sc.substance_id,
                volume_mL=vol,
                use_count=(lot.recovery_use_count or 0) if lot is not None else 0,
            )
        )

    # Worst case among the sources, plus this pass through the flask.
    use_count = max((s.use_count for s in shares), default=0) + 1

    # Composition. One component needs none: it is that solvent, whole.
    # With several, the operator's declared split wins; the quantities
    # that went in only ever suggested it, because recovery is not
    # proportional (see suggested_percentages).
    if len(shares) == 1:
        shares[0].raw_percent = 100.0
    elif percentages:
        missing = [s for s in shares if percentages.get(s.component.id) is None]
        if missing:
            raise RecoveryError("Indica la percentuale di ogni componente selezionato.")
        for s in shares:
            pct = percentages[s.component.id]
            if pct < 0:
                raise RecoveryError("Le percentuali non possono essere negative.")
            s.raw_percent = float(pct)
        if sum(s.raw_percent for s in shares) <= _EPS:
            raise RecoveryError("La somma delle percentuali deve essere maggiore di zero.")
    else:
        suggestion = suggested_percentages([s.component for s in shares])
        if suggestion is None:
            raise RecoveryError(
                "Indica la composizione del solvente recuperato, oppure "
                "registra le quantità reali dei componenti."
            )
        for s in shares:
            s.raw_percent = suggestion[s.component.id]

    shares = _rounded_shares(shares)
    single = len(shares) == 1

    mixture: Mixture | None = None
    reused = False
    if single:
        substance_id = shares[0].substance_id
    else:
        substance_id = None
        signature = composition_signature(shares)
        mixture = db.session.query(Mixture).filter_by(recovery_signature=signature).first()
        if mixture is None:
            mixture = Mixture(
                name=composition_name(shares),
                kind=MIXTURE_KIND_ELUENT if len(shares) > 1 else MIXTURE_KIND_SOLUTION,
                recovery_signature=signature,
                is_recovered=True,
                is_active=True,
                created_by_id=user_id,
                description=(
                    "Anagrafica creata automaticamente dal recupero solvente. "
                    f"Composizione arrotondata a passi del {COMPOSITION_STEP_PCT:g}% v/v."
                ),
            )
            db.session.add(mixture)
            db.session.flush()
            for pos, s in enumerate(shares):
                db.session.add(
                    MixtureComponent(
                        mixture_id=mixture.id,
                        substance_id=s.substance_id,
                        role=COMPONENT_ROLE_SOLVENT,
                        concentration=s.percent,
                        concentration_unit="%v/v",
                        position=pos,
                    )
                )
        else:
            reused = True

    # Ownership follows the lots the solvent came from, like a prep
    # does. When none of the ticked components is bound to a lot there
    # is nothing to inherit — and that is fine, not an error: the
    # ``before_insert`` hook on InventoryItem assigns the Default group.
    # Refusing here (as v1.5.1 did) blocked a perfectly ordinary
    # recovery from a solvent whose lot was never recorded.
    group_id = None
    for s in shares:
        src = (
            db.session.get(InventoryItem, s.component.inventory_item_id)
            if s.component.inventory_item_id
            else None
        )
        if src is not None and src.group_id is not None:
            group_id = src.group_id
            break

    lot = InventoryItem(
        substance_id=substance_id,
        mixture_id=mixture.id if mixture is not None else None,
        batch_code=_recovery_batch_code(run, step),
        quantity_mL=volume_mL,
        initial_quantity_mL=volume_mL,
        group_id=group_id,
        is_active=True,
        source_run_id=run.id,
        is_recovered=True,
        recovery_use_count=use_count,
        recovered_at=_now_utc(),
        recovered_from_step_id=step.id,
        origin_reaction_id=run.reaction_id,
        location=location,
        total_cost_eur=0.0,
        notes=(
            f"Recuperato da {run.code} — {step.title}. "
            f"Riutilizzabile solo nella stessa reazione. Usi: {use_count}."
        ),
    )
    db.session.add(lot)
    db.session.flush()

    return RecoveryResult(
        lot=lot,
        mixture=mixture,
        shares=shares,
        use_count=use_count,
        reused_catalogue_entry=reused,
    )


def _recovery_batch_code(run, step: RunStep) -> str:
    """``RX-2026-0444-REC1`` — run code plus a per-run sequence.

    Readable on a handwritten label, and sorts next to the run it came
    from in any listing.
    """
    base = f"{run.code}-REC"
    existing = (
        db.session.query(InventoryItem)
        .filter(InventoryItem.source_run_id == run.id)
        .filter(InventoryItem.is_recovered.is_(True))
        .count()
    )
    return f"{base}{existing + 1}"
