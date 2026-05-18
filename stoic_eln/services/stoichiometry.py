"""Stoic ELN — Stoichiometry calculator.

Given a reagent's molecular weight (MW) and optional density (ρ), and any one of
{equivalents, mmol, g, mL}, compute the others. The "limiting reagent" anchors
the equivalents axis: by convention it has eq=1.

Conventions:
- mmol = (g * 1000) / MW           or  g = mmol * MW / 1000
- mL   = g / density               or  g = mL * density
- mmol_other = eq_other * mmol_limiting
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Quantity:
    """A coherent set of {eq, mmol, g, mL} values (any may be None)."""

    equivalents: float | None = None
    mmol: float | None = None
    g: float | None = None
    mL: float | None = None


def from_g(g: float, mw: float | None, density: float | None) -> Quantity:
    """Compute the other fields starting from grams."""
    q = Quantity(g=g)
    if mw and mw > 0:
        q.mmol = g * 1000.0 / mw
    if density and density > 0:
        q.mL = g / density
    return q


def from_mL(mL: float, mw: float | None, density: float | None) -> Quantity:
    """Compute the other fields starting from millilitres."""
    q = Quantity(mL=mL)
    if density and density > 0:
        q.g = mL * density
        if mw and mw > 0:
            q.mmol = q.g * 1000.0 / mw
    return q


def from_mmol(mmol: float, mw: float | None, density: float | None) -> Quantity:
    """Compute the other fields starting from millimoles."""
    q = Quantity(mmol=mmol)
    if mw and mw > 0:
        q.g = mmol * mw / 1000.0
        if density and density > 0:
            q.mL = q.g / density
    return q


def from_equivalents(
    eq: float,
    limiting_mmol: float | None,
    mw: float | None,
    density: float | None,
) -> Quantity:
    """Compute the others from equivalents (relative to the limiting reagent).

    Requires the absolute mmol of the limiting reagent.
    """
    q = Quantity(equivalents=eq)
    if limiting_mmol is None or limiting_mmol <= 0:
        return q
    q.mmol = eq * limiting_mmol
    if mw and mw > 0:
        q.g = q.mmol * mw / 1000.0
        if density and density > 0:
            q.mL = q.g / density
    return q


def derive(
    *,
    mw: float | None,
    density: float | None,
    limiting_mmol: float | None = None,
    equivalents: float | None = None,
    mmol: float | None = None,
    g: float | None = None,
    mL: float | None = None,
) -> Quantity:
    """Best-effort derivation: pick the most authoritative input and fill in.

    Priority order: explicit `g` > `mL` > `mmol` > `equivalents` (the latter only
    works if `limiting_mmol` is provided).
    """
    if g is not None and g > 0:
        return from_g(g, mw, density)
    if mL is not None and mL > 0:
        return from_mL(mL, mw, density)
    if mmol is not None and mmol > 0:
        return from_mmol(mmol, mw, density)
    if (
        equivalents is not None
        and equivalents > 0
        and limiting_mmol is not None
        and limiting_mmol > 0
    ):
        return from_equivalents(equivalents, limiting_mmol, mw, density)
    return Quantity(
        equivalents=equivalents, mmol=mmol, g=g, mL=mL
    )


def equivalents_from_mmol(component_mmol: float, limiting_mmol: float) -> float | None:
    """Inverse: how many equivalents are X mmol relative to the limiting reagent?"""
    if limiting_mmol is None or limiting_mmol <= 0:
        return None
    return component_mmol / limiting_mmol
