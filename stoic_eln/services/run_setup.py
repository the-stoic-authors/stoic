"""Stoic ELN — Run setup service.

Logic for creating, editing, validating, and starting Run records.

Lifecycle:
  - create_draft(reaction, operator)  → instantiates a Run from the
    template, copying components, steps, and checklist items into
    snapshot tables. Returns a draft Run.
  - recompute_targets(run)            → updates target_mass/volume on
    every component based on the current scale_mmol.
  - start_run(run)                    → validates lots + actuals,
    deducts inventory (main components AND any step quantity already
    filled in), transitions to in_progress. Returns the list of step
    deductions so the caller can report short lots.
  - complete_run(run, yield_g)        → marks completed, computes %.
"""

from __future__ import annotations

from datetime import date, datetime, UTC

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.run import (
    STATUS_COMPLETED,
    STATUS_DRAFT,
    STATUS_IN_PROGRESS,
    Run,
)
from stoic_eln.models.run_component import RunComponent
from stoic_eln.models.run_step import RunChecklistItem, RunStep, RunStepComponent, RunStepParameter
from stoic_eln.models.user import User
from stoic_eln.services import run_code as run_code_service


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ─── Creation ───────────────────────────────────────────────────────────────


def create_draft(reaction: Reaction, operator: User | None = None) -> Run:
    """Create a draft Run from a published reaction template.

    Snapshots template components, steps, step-components, and checklists
    into the run's own tables. Caller commits the session.
    """
    if reaction.status != "published":
        raise ValueError("Run può essere creato solo da un template pubblicato.")

    # Generate the run code based on the operator + template + year
    op_code = (operator.operator_code if operator else "??") or "??"
    tem_code = reaction.template_code or reaction.code or "??"
    year = date.today().year
    code, seq = run_code_service.generate_run_code(
        op=op_code,
        tem=tem_code,
        year=year,
    )

    run = Run(
        code=code,
        sequence=seq,
        year=year,
        operator_code=op_code,
        template_code=tem_code,
        reaction_id=reaction.id,
        template_code_snapshot=reaction.template_code or reaction.code,
        template_title_snapshot=reaction.title,
        status=STATUS_DRAFT,
        operator_id=operator.id if operator else None,
        planned_date=date.today(),
    )
    db.session.add(run)
    db.session.flush()  # ensure run.id is available

    # Copy reaction-level components
    comp_map: dict[int, RunComponent] = {}
    for c in reaction.components:
        rc = RunComponent(
            run_id=run.id,
            template_component_id=c.id,
            substance_id=c.substance_id,
            mixture_id=c.mixture_id,
            role=c.role,
            is_limiting=c.is_limiting,
            track_in_inventory=c.track_in_inventory,
            equivalents=c.equivalents,
            concentration_M=c.concentration_M,
            position=c.position,
        )
        db.session.add(rc)
        comp_map[c.id] = rc

    # Copy reaction-level checklist items (default not done)
    for item in reaction.checklist_items:
        rci = RunChecklistItem(
            run_id=run.id,
            text=item.text,
            position=item.position,
            is_done=False,
        )
        db.session.add(rci)

    # Copy steps + their components + their checklists
    for step in reaction.steps:
        # Resolve the step's reference component to its RunComponent
        # snapshot (P2b). NULL on the template → leave NULL here, so
        # the calc falls back to the run's limiting reagent.
        ref_rc = None
        if step.reference_component_id is not None:
            ref_rc = comp_map.get(step.reference_component_id)

        rs = RunStep(
            run_id=run.id,
            template_step_id=step.id,
            title=step.title,
            kind=step.kind,
            description=step.description,
            position=step.position,
            reference_run_component=ref_rc,
        )
        db.session.add(rs)
        db.session.flush()

        for sc in step.components:
            db.session.add(
                RunStepComponent(
                    step_id=rs.id,
                    substance_id=sc.substance_id,
                    mixture_id=sc.mixture_id,
                    free_name=sc.free_name,
                    free_unit=sc.free_unit,
                    role=sc.role,
                    ratio_value=sc.ratio_value,
                    ratio_kind=sc.ratio_kind,
                    position=sc.position,
                )
            )

        for it in step.checklist_items:
            db.session.add(
                RunChecklistItem(
                    step_id=rs.id,
                    text=it.text,
                    position=it.position,
                    is_done=False,
                )
            )

        for prm in step.parameters:
            db.session.add(
                RunStepParameter(
                    step_id=rs.id,
                    label=prm.label,
                    unit=prm.unit,
                    position=prm.position,
                    value=None,
                )
            )

    db.session.flush()
    return run


# ─── Target computation ──────────────────────────────────────────────────────


def _mixture_concentration_M(c) -> float | None:
    """For a mixture-backed run component, return its effective
    concentration expressed in M (mol/L), or None if can't.

    Mirrors the unit conversion in services.reaction_stoich:
      * M, mM → direct
      * N → treated as M (true for monobasic acids/bases)
      * g/L, mg/mL, %w/v → divide by MW
      * %v/v, %w/w, ppm, ratio → no conversion (None)
    """
    if c.mixture is None:
        return None
    from stoic_eln.models.mixture import COMPONENT_ROLE_SOLUTE

    # Find concentration + unit (mixture primary, else solute component)
    conc = c.mixture.primary_concentration
    unit = c.mixture.primary_concentration_unit
    if conc is None or not unit:
        for mc in c.mixture.components:
            if mc.role == COMPONENT_ROLE_SOLUTE and mc.concentration is not None:
                conc = mc.concentration
                unit = mc.concentration_unit
                break
    if conc is None or not unit:
        return None

    if unit == "M":
        return conc
    if unit == "mM":
        return conc / 1000.0
    if unit == "N":
        return conc  # monobasic assumption
    sub = c.effective_substance
    if sub is None or not sub.molecular_weight:
        return None
    if unit == "g/L":
        return conc / sub.molecular_weight
    if unit == "mg/mL":
        # mg/mL = g/L numerically, divided by MW (g/mol) gives M
        return conc / sub.molecular_weight
    if unit == "%w/v":
        # 10% w/v = 10 g per 100 mL = 100 g/L
        g_per_L = conc * 10.0
        return g_per_L / sub.molecular_weight
    return None


def recompute_targets(run: Run) -> None:
    """Recompute the target_mass_g / target_volume_mL on every component.

    Driven by ``run.scale_mmol`` (mmol of the limiting reagent).
    For each component:
      - product / byproduct  → no target
      - solvent              → target_volume_mL from concentration_M
      - mixture-backed       → target_volume_mL = mmol / concentration_M
                              (the mixture's effective concentration
                              converted to M; see _mixture_concentration_M)
      - solid (default)      → target_mass_g = scale × eq × MW / 1000
      - liquid (with density)→ target_volume_mL = mass / density
                              (i.e. so the operator can pipette)

    "Liquid" = substance.state == 'liquid', or unknown state with a
    known density (see units.is_liquid).
    """
    from stoic_eln.services import units

    if run.scale_mmol is None:
        for c in run.components:
            c.target_mass_g = None
            c.target_volume_mL = None
        return

    scale = run.scale_mmol  # mmol

    for c in run.components:
        c.target_mass_g = None
        c.target_volume_mL = None

        sub = c.effective_substance
        if c.role in ("product", "byproduct"):
            # Theoretical mass: assume 1:1 stoichiometry with the limiting
            # reagent. Useful as a target/placeholder for the operator.
            if sub and sub.molecular_weight:
                c.target_mass_g = scale * sub.molecular_weight / 1000.0
            continue

        # Mixture-backed component: compute volume from molar amount
        # divided by the mixture's effective concentration (in M).
        # This is the canonical "use 5 mL of HCl 1N to get 5 mmol HCl"
        # use case driving patch 13.5.
        if c.mixture_id is not None:
            if not c.equivalents:
                continue
            mmol = scale * c.equivalents
            M = _mixture_concentration_M(c)
            if M and M > 0:
                # mmol / (mol/L) = mL  because mmol/M = (mol/1000) / (mol/L) = L/1000 = mL
                c.target_volume_mL = mmol / M
            # else: leave None — UI will surface as "compila a mano"
            continue

        if c.role == "solvent":
            if c.concentration_M and c.concentration_M > 0:
                # mmol / (mol/L) = mL exactly because mmol/M = mL.
                c.target_volume_mL = scale / c.concentration_M
            continue

        # Non-solvent substance component: SM, reagent, catalyst, base, …
        if sub is None or not sub.molecular_weight or not c.equivalents:
            continue
        mmol = scale * c.equivalents
        mass_g = mmol * sub.molecular_weight / 1000.0

        # Liquid with known density → display in volume; otherwise mass.
        if units.is_liquid(sub) and sub.density and sub.density > 0:
            c.target_volume_mL = mass_g / sub.density
        else:
            c.target_mass_g = mass_g


# ─── Validation + transition to in_progress ─────────────────────────────────


class RunStartError(Exception):
    """Raised when a run cannot transition to in_progress."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


def validate_for_start(run: Run) -> list[str]:
    """Return a list of human-readable errors blocking the start.

    Empty list ⇒ run is ready to start.
    """
    errors: list[str] = []

    if run.status != STATUS_DRAFT:
        errors.append("Solo le bozze possono essere avviate.")
        return errors

    if run.scale_mmol is None or run.scale_mmol <= 0:
        errors.append("Scala (mmol del limitante) non impostata.")

    for c in run.components:
        if c.role in ("product", "byproduct"):
            continue
        # display_name handles both substance- and mixture-backed
        # components transparently, so the error messages read
        # naturally for either kind.
        sub_name = c.display_name
        if c.inventory_item_id is None:
            errors.append(f"Manca il lotto per {sub_name}.")
            continue
        if c.actual_mass_g is None and c.actual_volume_mL is None:
            errors.append(f"Manca il peso/volume reale per {sub_name}.")
            continue
        # Verify that the lot has enough quantity
        lot = c.inventory_item
        if lot is None:
            errors.append(f"Lotto non trovato per {sub_name}.")
            continue
        if c.actual_mass_g is not None:
            if lot.quantity_g is None or lot.quantity_g < c.actual_mass_g:
                errors.append(
                    f"Lotto di {sub_name}: disponibili "
                    f"{lot.quantity_g or 0:g} g, richiesti {c.actual_mass_g:g} g."
                )
        if c.actual_volume_mL is not None:
            if lot.quantity_mL is None or lot.quantity_mL < c.actual_volume_mL:
                errors.append(
                    f"Lotto di {sub_name}: disponibili "
                    f"{lot.quantity_mL or 0:g} mL, richiesti {c.actual_volume_mL:g} mL."
                )

    return errors


def start_run(run: Run) -> list:
    """Deduct inventory and transition the run to in_progress.

    Raises RunStartError if validation fails. On success, all bound
    inventory lots are decremented atomically inside the current
    session (caller commits).

    Step components whose quantity was already filled in during draft
    are deducted here too (v1.4.4) — from this moment on they stay in
    sync incrementally, on every edit. Returns the list of
    ``StepDeduction`` results so the caller can surface any lot that
    ran short; the main-component deductions still raise instead,
    because those are validated up front.
    """
    errors = validate_for_start(run)
    if errors:
        raise RunStartError("Run non avviabile.", errors=errors)

    for c in run.components:
        if c.role in ("product", "byproduct"):
            continue
        if c.actual_mass_g is not None:
            ok = c.inventory_item.use_quantity(c.actual_mass_g, "g")
            if not ok:
                raise RunStartError(f"Quantità insufficiente nel lotto di {c.display_name}.")
        elif c.actual_volume_mL is not None:
            ok = c.inventory_item.use_quantity(c.actual_volume_mL, "mL")
            if not ok:
                raise RunStartError(f"Quantità insufficiente nel lotto di {c.display_name}.")

    run.status = STATUS_IN_PROGRESS
    run.started_at = _now_utc()

    # The run is live now, so step quantities entered during draft
    # become real consumption. Done after the status flip because the
    # sync reads it to decide whether anything should be held.
    from stoic_eln.services.step_inventory import sync_run_step_inventory

    return sync_run_step_inventory(run)


# ─── Completion ─────────────────────────────────────────────────────────────


class RunCompleteWarning:
    """Warning levels emitted by complete_run."""

    YIELD_OVER_100 = "yield_over_100"
    NO_PRODUCT_WEIGHT = "no_product_weight"


def complete_run(run: Run, *, force_no_products: bool = False) -> dict:
    """Mark a run as completed using the actual_mass_g of its products.

    The yield is now derived from the product components' ``actual_mass_g``
    (set via the same UI pattern as the other components, during the
    in_progress phase).

    For each product with ``actual_mass_g > 0``, this function creates a
    new InventoryItem with batch_code ``<run.code>-P<n>`` and
    ``source_run_id = run.id``.

    If NO product has a mass set, the run is treated as "failed":
      - the caller must pass ``force_no_products=True`` to confirm
      - status becomes COMPLETED with yield_g=0
      - no inventory lots are created

    Returns a dict with diagnostic info:
      {
        "warnings": [...],   # list of strings (yield_over_100, etc.)
        "lots_created": [    # InventoryItem objects (not yet committed)
            {"product_name": str, "batch_code": str, "quantity_g": float},
            ...
        ],
        "yield_percent": float | None,
        "is_failed": bool,
      }
    """
    if run.status != STATUS_IN_PROGRESS:
        raise ValueError("Solo i run in esecuzione possono essere completati.")

    products = [c for c in run.components if c.role in ("product", "byproduct")]
    # "Real" products count toward yield and inventory; components flagged
    # track_in_inventory=False are waste (e.g. NaHSO4) and are excluded from
    # both the yield and the lot creation below. Yield is on the product,
    # not on the scraps.
    real_products = [p for p in products if getattr(p, "track_in_inventory", True)]
    products_with_mass = [p for p in real_products if p.actual_mass_g and p.actual_mass_g > 0]

    warnings: list[str] = []
    lots_created: list[dict] = []

    # Caso: nessun peso prodotto inserito
    if real_products and not products_with_mass:
        if not force_no_products:
            raise RunStartError(
                "Pesi dei prodotti non inseriti.",
                errors=[
                    "Pesi dei prodotti non inseriti. Confermare per "
                    "registrare il run come fallito (resa zero)."
                ],
            )
        run.yield_g = 0.0
        run.yield_percent = 0.0
        warnings.append(RunCompleteWarning.NO_PRODUCT_WEIGHT)
        run.status = STATUS_COMPLETED
        run.completed_at = _now_utc()
        return {
            "warnings": warnings,
            "lots_created": lots_created,
            "yield_percent": 0.0,
            "is_failed": True,
        }

    # Caso normale: almeno un prodotto pesato
    # Total yield = sum of REAL product masses (scraps excluded)
    total_yield_g = sum(p.actual_mass_g for p in products_with_mass)
    run.yield_g = total_yield_g

    # Theoretical yield is based on the FIRST real product's MW × scale
    # (1:1 stoichiometry assumed). Scraps are never the main product.
    theoretical_g = None
    if real_products and run.scale_mmol:
        main_prod = sorted(real_products, key=lambda p: p.position)[0]
        if main_prod.substance and main_prod.substance.molecular_weight:
            theoretical_g = run.scale_mmol * main_prod.substance.molecular_weight / 1000.0

    if theoretical_g and theoretical_g > 0:
        run.yield_percent = (total_yield_g / theoretical_g) * 100.0
        if run.yield_percent > 100.0:
            warnings.append(RunCompleteWarning.YIELD_OVER_100)
    else:
        run.yield_percent = None

    # Create inventory lots for each REAL product with mass.
    # Scraps (track_in_inventory=False) are already excluded from
    # real_products, so they never reach this loop.
    sorted_products = sorted(real_products, key=lambda p: p.position)
    p_index = 0
    created_lots = []  # (product_component, lot) pairs for cost allocation
    for p in sorted_products:
        if not p.actual_mass_g or p.actual_mass_g <= 0:
            continue
        p_index += 1
        batch_code = f"{run.code}-P{p_index}"
        lot = InventoryItem(
            substance_id=p.substance_id,
            batch_code=batch_code,
            quantity_g=p.actual_mass_g,
            initial_quantity_g=p.actual_mass_g,
            is_active=True,
            source_run_id=run.id,
        )
        db.session.add(lot)
        created_lots.append((p, lot))
        lots_created.append(
            {
                "product_name": p.substance.name if p.substance else "?",
                "batch_code": batch_code,
                "quantity_g": p.actual_mass_g,
            }
        )

    # ── Cost allocation (Settimana 6 patch 5.1) ────────────────────
    # Compute the run's cumulative cost (direct materials +
    # intermediate-lot costs consumed) and split it across the
    # product lots proportionally to mass — so that future runs that
    # consume these lots will inherit the upstream cost.
    if created_lots:
        # We need to flush so cost_per_unit/cost_per_mole work and
        # also so the cost computation can see the inventory_item_id
        # references on the consumed components.
        db.session.flush()
        from stoic_eln.services.run_cost import (
            compute_run_cost,
            compute_run_cost_cumulative,
        )

        bd = compute_run_cost(run)
        cum_total = compute_run_cost_cumulative(run, bd)
        if cum_total > 0:
            total_product_g = sum(p.actual_mass_g for p, _ in created_lots)
            for p, lot in created_lots:
                share = (p.actual_mass_g / total_product_g) if total_product_g else 0
                lot.total_cost_eur = round(cum_total * share, 4)

    run.status = STATUS_COMPLETED
    run.completed_at = _now_utc()

    return {
        "warnings": warnings,
        "lots_created": lots_created,
        "yield_percent": run.yield_percent,
        "is_failed": False,
    }


# ─── Clone a StepTemplate onto an existing run (P2c) ────────────────────────


def clone_template_step_to_run(template_id: int, run: Run) -> RunStep:
    """Copy a StepTemplate (procedure library entry) as a new RunStep
    appended to *run*.

    Clones components (substance/mixture/free XOR), checklist items, and
    parameters. template_step_id is left NULL because the source is a
    StepTemplate, not a ReactionStep — the field tracks reaction-template
    lineage only.

    Raises ValueError if the template does not exist.
    """
    from stoic_eln.models.step_template import StepTemplate

    tmpl = db.session.get(StepTemplate, template_id)
    if tmpl is None:
        raise ValueError(f"StepTemplate #{template_id} not found")

    existing_positions = [s.position for s in run.steps]
    position = (max(existing_positions) + 1) if existing_positions else 0

    rs = RunStep(
        run_id=run.id,
        template_step_id=None,
        title=tmpl.name,
        kind=tmpl.kind,
        description=tmpl.description,
        position=position,
    )
    db.session.add(rs)
    db.session.flush()

    for sc in tmpl.components:
        db.session.add(
            RunStepComponent(
                step_id=rs.id,
                substance_id=sc.substance_id,
                mixture_id=sc.mixture_id,
                free_name=sc.free_name,
                free_unit=sc.free_unit,
                role=sc.role,
                ratio_value=sc.ratio_value,
                ratio_kind=sc.ratio_kind,
                position=sc.position,
            )
        )

    for it in tmpl.checklist_items:
        db.session.add(
            RunChecklistItem(
                step_id=rs.id,
                text=it.text,
                position=it.position,
                is_done=False,
            )
        )

    for prm in tmpl.parameters:
        db.session.add(
            RunStepParameter(
                step_id=rs.id,
                label=prm.label,
                unit=prm.unit,
                position=prm.position,
                value=None,
            )
        )

    return rs
