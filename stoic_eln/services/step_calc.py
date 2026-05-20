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
    if run.scale_mmol is None or rsc.ratio_value is None:
        return StepQuantity()

    # Find the limiting reagent in the run's components
    limiting = next((c for c in run.components if c.is_limiting), None)
    if limiting is None or limiting.substance is None:
        return StepQuantity()

    sub = limiting.substance
    ref_mw = sub.molecular_weight
    ref_density = sub.density

    # Reference quantity = the limiting at run.scale_mmol (eq=1)
    ref_q = reference_quantities(
        ref_equivalents=1.0,
        scale_mmol=run.scale_mmol,
        ref_mw=ref_mw,
        ref_density=ref_density,
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
