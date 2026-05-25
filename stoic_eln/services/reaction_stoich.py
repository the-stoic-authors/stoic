"""Stoic ELN — Stoichiometry helpers for mixture-backed reaction components.

When a ReactionComponent points at a Mixture (e.g. "HCl 1N, 5 mL"
as a reagent), the moles of the active ingredient come from
``concentration × volume``, not from ``mass / MW`` as for substance
components. This module centralises that math so the form/editor
and the Run consumption logic compute consistent numbers.

Conversions implemented:

  * Molarity (M, mM)        — moles = M × V_L     (canonical)
  * Normality (N)           — equivalents = N × V_L
                              For monobasic acids/bases, N == M.
                              We treat N == M here (warning in caller).
  * Mass per volume (g/L,
    mg/mL)                  — mass = (g/L) × V_L,
                              then moles = mass / MW
  * Mass percentage (%w/v)  — mass = (g_per_100mL) × V_100mL,
                              then moles = mass / MW
  * Volume percentage (%v/v) — without density we can't convert to
                              moles. Returns None and the caller
                              must fall back to manual entry.

The intent is: the form auto-fills ``amount_mmol`` when the user
enters ``amount_mL`` on a mixture-backed component, but never
clobbers a manual override.
"""

from __future__ import annotations

from dataclasses import dataclass

from stoic_eln.models.reaction_component import ReactionComponent


@dataclass
class MmolFromVolumeResult:
    """Output of ``mmol_from_volume_mL``.

    ``mmol`` is None if the math couldn't be done (missing data,
    incompatible units like %v/v without density). ``reason``
    explains why so the UI can surface it.
    """

    mmol: float | None
    reason: str = ""  # empty when mmol is set


def mmol_from_volume_mL(
    component: ReactionComponent,
    volume_mL: float,
) -> MmolFromVolumeResult:
    """Compute moles (in mmol) of the active ingredient given a volume
    of a mixture-backed reaction component.

    Caller is responsible for ensuring ``component.mixture is not None``
    (this function gracefully returns ``mmol=None`` if it is, but
    that's a logic error upstream).
    """
    if component.mixture is None:
        return MmolFromVolumeResult(
            mmol=None,
            reason="Componente non basato su miscela.",
        )
    if volume_mL is None or volume_mL <= 0:
        return MmolFromVolumeResult(
            mmol=None,
            reason="Volume non specificato o non positivo.",
        )

    conc = component.effective_concentration
    unit = component.effective_concentration_unit
    if conc is None or not unit:
        return MmolFromVolumeResult(
            mmol=None,
            reason="Concentrazione della miscela non specificata.",
        )

    V_L = volume_mL / 1000.0

    if unit == "M":
        # moles = M × V_L; mmol = M × V_mL
        return MmolFromVolumeResult(mmol=conc * volume_mL)
    if unit == "mM":
        # moles = mM × 1e-3 × V_L; mmol = mM × V_L
        return MmolFromVolumeResult(mmol=conc * V_L)
    if unit == "N":
        # Treat N as M for stoichiometry — true for monobasic acids
        # (HCl, NaOH), wrong by a factor for H2SO4 / Ca(OH)2 / etc.
        # The form will surface a warning so the chemist can override.
        return MmolFromVolumeResult(
            mmol=conc * volume_mL,
            reason="Normalità trattata come molarità (vero per acidi/basi mono).",
        )
    if unit == "g/L":
        sub = component.effective_substance
        if sub is None or not sub.molecular_weight:
            return MmolFromVolumeResult(
                mmol=None,
                reason="MW del soluto non disponibile per conversione massica.",
            )
        mass_g = conc * V_L
        return MmolFromVolumeResult(
            mmol=(mass_g / sub.molecular_weight) * 1000.0,
        )
    if unit == "mg/mL":
        sub = component.effective_substance
        if sub is None or not sub.molecular_weight:
            return MmolFromVolumeResult(
                mmol=None,
                reason="MW del soluto non disponibile per conversione massica.",
            )
        # mg/mL × mL = mg → / MW (g/mol) = mmol directly
        mass_mg = conc * volume_mL
        return MmolFromVolumeResult(
            mmol=mass_mg / sub.molecular_weight,
        )
    if unit == "%w/v":
        # Defined as g per 100 mL: 10% w/v = 10 g per 100 mL = 100 g/L
        sub = component.effective_substance
        if sub is None or not sub.molecular_weight:
            return MmolFromVolumeResult(
                mmol=None,
                reason="MW del soluto non disponibile per conversione %w/v.",
            )
        mass_g = (conc / 100.0) * volume_mL  # g per mL × mL
        return MmolFromVolumeResult(
            mmol=(mass_g / sub.molecular_weight) * 1000.0,
        )
    if unit == "%v/v":
        return MmolFromVolumeResult(
            mmol=None,
            reason=(
                "Conversione %v/v → moli richiede densità del soluto, "
                "non disponibile. Compila a mano."
            ),
        )

    # Anything else (%w/w, ppm, ratio, …) — explicit fall-through.
    return MmolFromVolumeResult(
        mmol=None,
        reason=f"Conversione automatica non supportata per unità {unit!r}.",
    )
