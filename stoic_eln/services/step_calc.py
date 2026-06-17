"""Stoic ELN — Reaction step quantity calculator.

Computes the absolute quantities (g, mL, mmol) of step components based on:
  - the chosen reference (a ReactionComponent or the limiting reagent),
  - the reference's quantity at the current scale,
  - the ratio_kind + ratio_value of the step component.

The "current scale" is the reaction's `default_scale_mmol` (in template view)
or the run's `scale_mmol` (in run view, Week 4).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StepQuantity:
    """Computed quantities for a step component at a given scale."""

    g: float | None = None
    mL: float | None = None
    mmol: float | None = None
    #: Value in a component's own free unit (P2 free entries):
    #: fixed values and computed column diameters land here.
    free: float | None = None


def _ref_substance(comp):
    """Best substance to read MW/density from for a reference component.

    Mixture-backed components expose their primary solute via
    ``effective_substance``; substance-backed ones just have
    ``substance``. Returns None when neither is available.
    """
    if comp is None:
        return None
    return getattr(comp, "effective_substance", None) or getattr(comp, "substance", None)


def reference_quantities(
    *,
    ref_equivalents: float,
    scale_mmol: float,
    ref_mw: float | None,
    ref_density: float | None,
) -> StepQuantity:
    """Compute the reference component's absolute quantities at this scale.

    Given that the reference has `ref_equivalents` and the limiting reagent
    is at `scale_mmol`, derive ref_mmol → ref_g → ref_mL.
    """
    out = StepQuantity()
    out.mmol = ref_equivalents * scale_mmol
    if ref_mw and ref_mw > 0:
        out.g = out.mmol * ref_mw / 1000.0
        if ref_density and ref_density > 0:
            out.mL = out.g / ref_density
    return out


def compute_step_component(
    *,
    ratio_kind: str,
    ratio_value: float | None,
    ref_quantity: StepQuantity,
    sub_mw: float | None,
    sub_density: float | None,
) -> StepQuantity:
    """Compute the absolute quantity of a step component.

    Args:
        ratio_kind: One of:
            - 'eq': stoichiometric equivalents relative to reference
            - 'mL_per_g': mL per gram of reference (e.g. wash volume)
            - 'mL_per_mmol': mL per mmol of reference (e.g. solvent volume)
            - 'percent_vv': % v/v of reference volume (e.g. acid additives)
            - 'absolute_mL': fixed volume, independent of reference
            - 'absolute_g': fixed mass, independent of reference
        ratio_value: Numeric value (e.g. 3 for "3 eq", 10 for "10 mL/g",
            30 for "30 mL absolute").
        ref_quantity: The reference component's absolute quantities at
            scale. Ignored for 'absolute_mL' and 'absolute_g'.
        sub_mw, sub_density: Properties of the step component substance.
            Used to convert between mass / volume / mmol where possible.
    """
    if ratio_value is None:
        return StepQuantity()

    out = StepQuantity()

    if ratio_kind == "eq":
        # 3 eq of NaCl → mmol = 3 * ref_mmol
        if ref_quantity.mmol is None:
            return out
        out.mmol = ratio_value * ref_quantity.mmol
        if sub_mw and sub_mw > 0:
            out.g = out.mmol * sub_mw / 1000.0
            if sub_density and sub_density > 0:
                out.mL = out.g / sub_density

    elif ratio_kind == "mL_per_g":
        # 10 mL of water per gram of crude → mL = 10 * ref_g
        if ref_quantity.g is None:
            return out
        out.mL = ratio_value * ref_quantity.g
        if sub_density and sub_density > 0:
            out.g = out.mL * sub_density
            if sub_mw and sub_mw > 0:
                out.mmol = out.g * 1000.0 / sub_mw

    elif ratio_kind == "mL_per_mmol":
        # 20 mL of EtOAc per mmol of SM → mL = 20 * ref_mmol
        if ref_quantity.mmol is None:
            return out
        out.mL = ratio_value * ref_quantity.mmol
        if sub_density and sub_density > 0:
            out.g = out.mL * sub_density
            if sub_mw and sub_mw > 0:
                out.mmol = out.g * 1000.0 / sub_mw

    elif ratio_kind == "g_per_g":
        # X g of component per gram of the reference (mass:mass loading).
        # Pure mass ratio — no MW/density needed. DELIBERATELY g-only:
        # for the canonical use case (flash silica loading) converting
        # to mL via the substance density would yield the skeletal
        # volume, meaningless for bed packing. The column-diameter calc
        # applies a process bulk density (SILICA_BULK_DENSITY_G_PER_ML)
        # separately when it needs a bed volume.
        if ref_quantity.g is None:
            return out
        out.g = ratio_value * ref_quantity.g

    elif ratio_kind == "percent_vv":
        # 5 % v/v of TFA → mL = ref_mL * 5 / 100
        if ref_quantity.mL is None:
            return out
        out.mL = ref_quantity.mL * ratio_value / 100.0
        if sub_density and sub_density > 0:
            out.g = out.mL * sub_density
            if sub_mw and sub_mw > 0:
                out.mmol = out.g * 1000.0 / sub_mw

    elif ratio_kind == "absolute_mL":
        # User-fixed volume — independent of the reference. Common
        # for steps like "wash with 30 mL water" or "extract with
        # 20 mL EtOAc" where the volume is recipe-determined rather
        # than stoichiometric.
        out.mL = ratio_value
        if sub_density and sub_density > 0:
            out.g = out.mL * sub_density
            if sub_mw and sub_mw > 0:
                out.mmol = out.g * 1000.0 / sub_mw

    elif ratio_kind == "absolute_g":
        # User-fixed mass — same idea as absolute_mL but for solids
        # ("add 2.5 g Na2SO4 as drying agent").
        out.g = ratio_value
        if sub_density and sub_density > 0:
            out.mL = out.g / sub_density
        if sub_mw and sub_mw > 0:
            out.mmol = out.g * 1000.0 / sub_mw

    return out


def compute_run_step_component(rsc, run, *, fallback_ref_mmol=None) -> StepQuantity:
    """Compute absolute quantities for a RunStepComponent at run scale.

    The run's "reference" for step components is the LIMITING reagent
    of the run (from the templated components). We use the limiting's
    actual_mmol (if set) or the target scale.

    rsc: a RunStepComponent
    run: the parent Run (with scale_mmol set)
    Returns a StepQuantity with absolute g/mL/mmol.
    """
    # Free entries (P2): fixed_value carries its own number; the
    # column diameter is derived from the stationary phase in the
    # same step. Both bypass the reference machinery below. The
    # caller renders StepQuantity.free with rsc.free_unit.
    if getattr(rsc, "free_name", None):
        if rsc.ratio_kind == "fixed_value":
            return StepQuantity(free=rsc.ratio_value)
        if rsc.ratio_kind == "column_diameter_mm":
            silica = next(
                (c for c in rsc.step.components if c.role == "stationary_phase" and c.id != rsc.id),
                None,
            )
            if silica is None:
                return StepQuantity()
            silica_q = compute_run_step_component(silica, run, fallback_ref_mmol=fallback_ref_mmol)
            return StepQuantity(free=compute_column_diameter_mm(silica_q.g, rsc.ratio_value))
        return StepQuantity()

    if run.scale_mmol is None or rsc.ratio_value is None:
        return StepQuantity()

    # Resolve the reference component (P2b): the step's snapshotted
    # reference component if present (e.g. the product, for a flash
    # purification — gives "g per g of crude"), otherwise the run's
    # limiting reagent. We use the reference's own equivalents so the
    # reference mass scales correctly for non-limiting references.
    ref_comp = getattr(rsc.step, "reference_run_component", None)
    if ref_comp is None or _ref_substance(ref_comp) is None:
        ref_comp = next((c for c in run.components if c.is_limiting), None)
    if ref_comp is None:
        return StepQuantity()

    ref_sub = _ref_substance(ref_comp)
    if ref_sub is None:
        return StepQuantity()

    ref_q = reference_quantities(
        ref_equivalents=ref_comp.equivalents or 1.0,
        scale_mmol=run.scale_mmol,
        ref_mw=ref_sub.molecular_weight,
        ref_density=ref_sub.density,
    )

    sub_mw = rsc.substance.molecular_weight if rsc.substance else None
    sub_density = rsc.substance.density if rsc.substance else None

    return compute_step_component(
        ratio_kind=rsc.ratio_kind or "eq",
        ratio_value=rsc.ratio_value,
        ref_quantity=ref_q,
        sub_mw=sub_mw,
        sub_density=sub_density,
    )


# ── Column diameter (P2) ────────────────────────────────────────────

#: Bulk (tapped) density of dry flash-grade silica gel, g/mL.
#: 0.5 is the textbook figure for 40-63 µm irregular silica; vendors
#: quote 0.4-0.6 depending on grade. Used to convert silica mass to
#: bed volume when suggesting a column diameter.
SILICA_BULK_DENSITY_G_PER_ML = 0.5


def compute_column_diameter_mm(
    silica_g: float | None,
    bed_height_cm: float | None,
) -> float | None:
    """Suggest a column inner diameter for a given silica load.

    Geometry, nothing more: the bed is a cylinder of volume
    V = silica_g / bulk_density, and the operator wants it
    ``bed_height_cm`` tall, so

        d_cm = 2 * sqrt(V_mL / (pi * h_cm))      (1 mL = 1 cm³)

    Returned in mm because that's how chemists name columns
    ("a 30 mm column"). The caller rounds/picks the nearest column
    they actually own — we deliberately do NOT snap to a standard
    series here, because available glassware varies by lab.
    """
    if not silica_g or not bed_height_cm or silica_g <= 0 or bed_height_cm <= 0:
        return None
    import math

    volume_ml = silica_g / SILICA_BULK_DENSITY_G_PER_ML
    d_cm = 2.0 * math.sqrt(volume_ml / (math.pi * bed_height_cm))
    return d_cm * 10.0
