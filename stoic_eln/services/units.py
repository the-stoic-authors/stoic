"""Stoic ELN — Unit conversions and best-fit display.

Three jobs in this module:

1. **best_fit_mass(g)** / **best_fit_volume(mL)** — given an amount in
   the canonical SI-ish unit (g for masses, mL for volumes), return a
   (value, unit, formatted_string) tuple in the human-friendly unit:
   - mg if < 1 g, else g
   - mL if < 1 L, else L
   - 3 decimals always, trailing zeros kept (so "127.300 mg" not "127.3 mg")

2. **parse_scale(value, unit, *, substance)** — convert an operator-input
   pair like ("500", "mg") or ("3.5", "mL") into mmol (canonical scale
   for the limiting reagent). Liquids in volume units need substance
   density to convert to mass first.

3. **convert_to_canonical(amount, unit)** — convert any input back to
   the canonical unit (g for mass, mL for volume) for storage.

The "canonical" units we store on disk are always g and mL — best-fit
formatting is done at display time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stoic_eln.models.substance import Substance


# Allowed scale-input units (when entering the limiting reagent's scale)
SCALE_MASS_UNITS = ("mg", "g")
SCALE_VOLUME_UNITS = ("mL", "L")
SCALE_AMOUNT_UNITS = ("mmol", "mol")
ALL_SCALE_UNITS = SCALE_AMOUNT_UNITS + SCALE_MASS_UNITS + SCALE_VOLUME_UNITS


@dataclass(frozen=True)
class FormattedAmount:
    """A best-fit display of an amount.

    Attributes:
        value: numeric value in the human unit (e.g. 127.3 in "127.300 mg")
        unit: human unit ("mg" / "g" / "mL" / "L")
        formatted: pre-rendered string with 3 decimals (e.g. "127.300")
        unit_label: same as unit, but explicit (for templates)
    """
    value: float
    unit: str
    formatted: str

    @property
    def unit_label(self) -> str:
        return self.unit

    def __str__(self) -> str:
        return f"{self.formatted} {self.unit}"


def _fmt3(x: float) -> str:
    """Format with 3 decimals, keeping trailing zeros (e.g. '5.000')."""
    return f"{x:.3f}"


def best_fit_mass(grams: float | None) -> FormattedAmount | None:
    """Pick mg/g for a mass in grams, with 3-decimal formatting.

    - mg if < 1 g
    - g  if ≥ 1 g
    """
    if grams is None:
        return None
    if grams < 1.0:
        return FormattedAmount(value=grams * 1000.0, unit="mg",
                               formatted=_fmt3(grams * 1000.0))
    return FormattedAmount(value=grams, unit="g", formatted=_fmt3(grams))


def best_fit_volume(mL: float | None) -> FormattedAmount | None:
    """Pick mL/L for a volume in mL, with 3-decimal formatting.

    - mL if < 1000 mL
    - L  if ≥ 1000 mL
    """
    if mL is None:
        return None
    if mL < 1000.0:
        return FormattedAmount(value=mL, unit="mL", formatted=_fmt3(mL))
    return FormattedAmount(value=mL / 1000.0, unit="L",
                           formatted=_fmt3(mL / 1000.0))


# ─── Conversions to canonical (g, mL, mmol) ──────────────────────────


def to_grams(amount: float, unit: str) -> float:
    """Convert a mass amount in unit ('mg' or 'g') to grams."""
    if unit == "g":
        return amount
    if unit == "mg":
        return amount / 1000.0
    raise ValueError(f"Not a mass unit: {unit!r}")


def to_mL(amount: float, unit: str) -> float:
    """Convert a volume amount in unit ('mL' or 'L') to mL."""
    if unit == "mL":
        return amount
    if unit == "L":
        return amount * 1000.0
    raise ValueError(f"Not a volume unit: {unit!r}")


def to_mmol(amount: float, unit: str) -> float:
    """Convert an amount-of-substance in unit ('mmol' or 'mol') to mmol."""
    if unit == "mmol":
        return amount
    if unit == "mol":
        return amount * 1000.0
    raise ValueError(f"Not an amount unit: {unit!r}")


# ─── Scale parsing (operator input → mmol) ──────────────────────────


class ScaleConversionError(ValueError):
    """Raised when a scale input cannot be converted to mmol.

    Typical reasons:
      - mass unit but substance has no MW
      - volume unit but substance has no density (and is not in mol/L mode)
      - bad numeric input
    """


def parse_scale_to_mmol(
    amount: float,
    unit: str,
    *,
    substance: "Substance | None" = None,
) -> float:
    """Convert an operator-entered scale into mmol of the limiting reagent.

    Logic:
      - mmol/mol             → direct conversion, no substance needed
      - mg/g                 → needs substance.molecular_weight
      - mL/L                 → needs substance.density (g/mL) AND
                               substance.molecular_weight to get to mmol
    """
    if unit in SCALE_AMOUNT_UNITS:
        return to_mmol(amount, unit)

    if substance is None:
        raise ScaleConversionError(
            "Conversione di massa/volume richiede una sostanza con MW"
            " (e densità per i liquidi)."
        )
    mw = substance.molecular_weight
    if mw is None or mw <= 0:
        raise ScaleConversionError(
            f"La sostanza {substance.name!r} non ha MW: impossibile convertire."
        )

    if unit in SCALE_MASS_UNITS:
        grams = to_grams(amount, unit)
        # mmol = g / (g/mol) × 1000
        return grams / mw * 1000.0

    if unit in SCALE_VOLUME_UNITS:
        density = substance.density
        if density is None or density <= 0:
            raise ScaleConversionError(
                f"La sostanza {substance.name!r} non ha densità:"
                " impossibile convertire da volume a mmol."
            )
        mL = to_mL(amount, unit)
        grams = mL * density
        return grams / mw * 1000.0

    raise ScaleConversionError(f"Unità non riconosciuta: {unit!r}")


# ─── Substance-state-aware target unit picking ──────────────────────


def is_liquid(substance: "Substance | None") -> bool:
    """Heuristic: treat anything explicitly liquid (or with a density
    and no explicit solid state) as a liquid.

    Used to decide whether a non-solvent reagent should be displayed
    in a volume unit.
    """
    if substance is None:
        return False
    if substance.state == "liquid":
        return True
    if substance.state == "solid":
        return False
    # Unknown state: liquid if density is set and there's no MP info
    # suggesting solid at RT. We're conservative: only call it liquid
    # if state is explicitly None and density is set.
    if substance.state is None and substance.density:
        return True
    return False
