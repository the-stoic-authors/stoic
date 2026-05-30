"""Stoic ELN — Inventory quantity unit policy.

Single source of truth for the matrix that decides which units an
inventory lot can be expressed in, given its substance's properties.

The rule, in chemical terms:

  - Stoichiometry is computed on mass. So a **reagent** must be
    expressible in grams.
  - Volume is meaningful only when (a) the substance is a solvent,
    where mL dosing is standard practice, or (b) we know the density
    and can therefore convert between mass and volume on demand.

This collapses into four cases, indexed by ``is_solvent`` and
whether ``density`` is known:

  ┌──────────────────────────┬───────────┬──────────┬────────────────┐
  │ Substance                │ is_solvent│ density  │ Editable units │
  ├──────────────────────────┼───────────┼──────────┼────────────────┤
  │ Reagent solid/no-density │   False   │   None   │  only g        │
  │ Reagent with density     │   False   │ settable │  g + mL synced │
  │ Solvent without density  │   True    │   None   │  only mL       │
  │ Solvent with density     │   True    │ settable │  g + mL synced │
  └──────────────────────────┴───────────┴──────────┴────────────────┘

Key invariant: for any inventory item, ``quantity_g`` and
``quantity_mL`` (and similarly the initial pair) either represent
the same physical amount (when both are set, related by density),
or exactly one is set with the other NULL. Two independent values
would mean the warehouse counts the same bottle twice.

This module is consumed by:
  - The inventory create/edit routes (validation + normalisation
    before writing to the DB)
  - The one-shot migration script that fixes existing rows
  - The inventory form template (via a small Jinja helper that
    reads the policy to decide which fields to disable)

For mixtures (lots whose ``mixture_id`` is set), we apply a
permissive policy: the recipe already constrains how the mixture
behaves, and not all mixtures carry their own density. Mixture
lots may have either unit independently and the matrix above does
not apply to them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stoic_eln.models import InventoryItem, Substance


# Tolerance for "are these two values consistent with the density?"
# 0.5% covers normal numeric jitter from manual entry and round-trip
# divisions/multiplications without accepting genuinely wrong pairs.
_CONSISTENCY_TOL = 0.005


@dataclass(frozen=True)
class UnitPolicy:
    """The unit policy for a given substance, computed once."""

    allow_g: bool
    allow_mL: bool
    synced: bool  # if True, g and mL must be kept in lockstep via density
    density: float | None  # g/mL, or None if not known
    reason: str  # human-readable label, used as a debug hint

    @property
    def is_solid_or_no_density(self) -> bool:
        """The reagent-without-density case: only g."""
        return self.allow_g and not self.allow_mL

    @property
    def is_solvent_no_density(self) -> bool:
        """The solvent-without-density case: only mL."""
        return self.allow_mL and not self.allow_g

    @property
    def is_dual_synced(self) -> bool:
        """Both units available, kept in sync via density."""
        return self.synced


def policy_for_substance(substance: Substance | None) -> UnitPolicy:
    """Compute the unit policy for a substance.

    A ``None`` substance (which happens for mixture lots in some
    callers) yields a permissive "both allowed, not synced" policy
    — mixtures aren't subject to the matrix, so callers should
    branch on whether they're dealing with a substance or a mixture
    BEFORE invoking this. We return permissive defaults instead of
    raising so accidental misuse degrades gracefully.

    A density value alone does NOT make a substance volume-dosable:
    a salt like sodium sulphate has a published density (~2.66 g/cm³,
    its crystal density) but you don't measure it in mL because at
    room temperature it's a solid powder. We therefore check the
    inferred physical state via :py:meth:`Substance.detect_state` —
    if it comes back as ``"solid"``, the density is ignored for
    policy purposes regardless of the ``is_solvent`` flag.

    Why no override even for ``is_solvent=True``: by definition a
    solvent at the temperature of use is a liquid. A substance with
    a melting point above room temperature isn't a "solvent" in the
    chemical sense — at most it's a melt or an alloy, which Stoic
    doesn't try to model. If the operator has flagged a solid as a
    solvent, that's a catalog error, not a use case we accommodate.
    """
    if substance is None:
        return UnitPolicy(
            allow_g=True,
            allow_mL=True,
            synced=False,
            density=None,
            reason="no_substance",
        )

    is_solvent = bool(getattr(substance, "is_solvent", False))
    density = getattr(substance, "density", None)
    if density is not None and density <= 0:
        density = None  # treat zero / negative as "unset"

    # If density is set but the substance is solid at room temperature,
    # ignore the density for policy purposes regardless of is_solvent.
    # A solid powder isn't going into a syringe even if someone has
    # mis-flagged it as a solvent.
    if density is not None:
        try:
            inferred_state = substance.detect_state()
        except Exception:
            inferred_state = None
        if inferred_state == "solid":
            density = None  # downgrade to "no usable density"

    if is_solvent and density is None:
        return UnitPolicy(
            allow_g=False,
            allow_mL=True,
            synced=False,
            density=None,
            reason="solvent_no_density",
        )
    if not is_solvent and density is None:
        return UnitPolicy(
            allow_g=True,
            allow_mL=False,
            synced=False,
            density=None,
            reason="reagent_no_density",
        )
    # Both branches below have density set
    return UnitPolicy(
        allow_g=True,
        allow_mL=True,
        synced=True,
        density=density,
        reason=("solvent_with_density" if is_solvent else "reagent_with_density"),
    )


def policy_for_item(item: InventoryItem) -> UnitPolicy:
    """Compute the policy for an existing inventory item."""
    return policy_for_substance(item.substance)


def is_mixture_lot(item: InventoryItem) -> bool:
    """Mixture lots bypass the matrix (see module docstring)."""
    return getattr(item, "mixture_id", None) is not None


def normalize_pair(
    q_g: float | None,
    q_mL: float | None,
    policy: UnitPolicy,
) -> tuple[float | None, float | None, str | None]:
    """Apply the policy to a (g, mL) pair, returning the normalised pair.

    Returns ``(q_g, q_mL, error_message)``. If ``error_message`` is
    not None, the caller should refuse the write (validation error).

    Rules applied:
      - Reagent-no-density: mL must be empty. If filled, error.
      - Solvent-no-density: g must be empty. If filled, error.
      - Dual-synced: if both empty, returns (None, None) — no quantity
        yet, that's fine. If exactly one is set, the other is
        computed via density. If both are set, they must agree
        within ``_CONSISTENCY_TOL`` — otherwise error.
    """
    if not policy.allow_mL and q_mL is not None:
        return (
            q_g,
            None,
            ("Questa sostanza non è un solvente e non ha densità: compila solo i grammi."),
        )
    if not policy.allow_g and q_g is not None:
        return None, q_mL, ("Solvente senza densità: compila solo i millilitri.")

    if not policy.synced:
        # Either single-unit case; let the allowed value through.
        return q_g, q_mL, None

    # Dual-synced
    d = policy.density
    if d is None or d <= 0:
        # Defensive: shouldn't happen for synced policy
        return q_g, q_mL, None

    if q_g is None and q_mL is None:
        return None, None, None
    if q_g is not None and q_mL is None:
        return q_g, q_g / d, None
    if q_g is None and q_mL is not None:
        return q_mL * d, q_mL, None

    # Both set: must agree within tolerance
    expected_mL = q_g / d
    if expected_mL <= 0:
        return q_g, q_mL, None
    delta = abs(q_mL - expected_mL) / expected_mL
    if delta > _CONSISTENCY_TOL:
        return (
            q_g,
            q_mL,
            (
                f"Valori incoerenti: {q_g:g} g a densità {d:g} g/mL "
                f"corrispondono a {expected_mL:.3f} mL, ma è stato inserito "
                f"{q_mL:g} mL. Lascia uno dei due campi vuoto per il calcolo "
                "automatico."
            ),
        )
    return q_g, q_mL, None


def normalize_inventory_quantities(
    *,
    initial_g: float | None,
    initial_mL: float | None,
    remaining_g: float | None,
    remaining_mL: float | None,
    substance: Substance | None,
) -> tuple[float | None, float | None, float | None, float | None, str | None]:
    """Normalise both pairs of an InventoryItem.

    Returns ``(init_g, init_mL, rem_g, rem_mL, error)``.

    If ``error`` is not None, the FIRST inconsistency found is
    reported and the caller should refuse the write. We don't try
    to collect all errors at once because the user only sees one
    form section at a time and that's the clearer UX.
    """
    policy = policy_for_substance(substance)

    init_g, init_mL, err = normalize_pair(initial_g, initial_mL, policy)
    if err is not None:
        return init_g, init_mL, remaining_g, remaining_mL, err

    rem_g, rem_mL, err = normalize_pair(remaining_g, remaining_mL, policy)
    if err is not None:
        return init_g, init_mL, rem_g, rem_mL, err

    return init_g, init_mL, rem_g, rem_mL, None
