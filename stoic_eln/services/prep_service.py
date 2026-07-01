"""Stoic ELN — Mixture preparation business logic.

Two responsibilities:

1. **Auto-suggest** — given a target Mixture and a target quantity,
   propose for each component:
     * the active inventory lot to draw from (the most-recent /
       largest one, with enough remaining quantity)
     * the volume/mass to consume

2. **Execute** — given the operator's choices (lot per component +
   quantities), perform the preparation in a single DB transaction:
     * decrement each precursor lot's remaining quantity
     * create the new output lot for the target mixture
     * insert the MixturePrep + MixturePrepConsumption records
     * generate the batch code via prep_code service

The math is intentionally simple. For solutions with a primary
solute concentration:

    V_solute_stock = V_target × C_target / C_stock
    V_solvent      = V_target − V_solute_stock

For multi-component eluents (cosolvents with %v/v):

    V_each = V_target × (component_pct / 100)

For mass-based mixtures (g/L, mg/mL): same shape, scaled by the
relevant concentration field. If the math can't be derived
(missing concentrations, mismatched units), we fall back to a
"target only" suggestion: zero quantities, and the operator fills
them in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.mixture import (
    COMPONENT_ROLE_SOLUTE,
    COMPONENT_ROLE_SOLVENT,
    Mixture,
    MixtureComponent,
)
from stoic_eln.models.mixture_prep import (
    MixturePrep,
    MixturePrepConsumption,
)


# ── Suggestion data shapes ─────────────────────────────────────────


@dataclass
class SuggestedConsumption:
    """One row in the auto-suggest output: which lot, how much.

    A component can target either a pure ``Substance`` or another
    ``Mixture`` (the child_mixture pattern — e.g. preparing HCl 6N
    by diluting HCl 12N). Exactly one of ``substance_id`` and
    ``mixture_id`` is set, mirroring the XOR on
    ``MixtureComponent`` itself. ``display_name`` is what to show
    in the UI regardless of which side is set.
    """

    component_id: int  # MixtureComponent.id from the recipe
    # XOR pair: exactly one is set
    substance_id: int | None
    mixture_id: int | None
    display_name: str  # the human label, regardless of kind
    role: str
    suggested_lot_id: int | None  # InventoryItem.id, or None if no lot
    suggested_quantity: float | None
    suggested_unit: str | None
    available_lots: list[LotSummary]  # all candidate lots, for the dropdown
    # Detected stock concentration of the suggested precursor lot.
    # Populated only for solute components when the chosen lot has
    # a known concentration (mixture lot whose primary_concentration
    # or matching MixtureComponent is set). The UI surfaces this as
    # "stock conc: 12 N (HCl 12N)" so the operator can confirm.
    stock_info: StockInfo | None = None

    @property
    def substance_name(self) -> str:
        """Backward-compat alias for templates that still read
        ``r.substance_name``. New code should prefer ``display_name``,
        which makes the substance-vs-mixture polymorphism explicit.
        """
        return self.display_name

    @property
    def is_mixture(self) -> bool:
        """True if this row's component points at a child Mixture."""
        return self.mixture_id is not None


@dataclass
class LotSummary:
    """Summary of a candidate precursor lot for the picker dropdown."""

    id: int
    batch_code: str
    quantity_remaining: float
    quantity_unit: str  # "g" or "mL"
    expiry_date: str | None  # ISO format, "" if none
    location: str | None


@dataclass
class SuggestionResult:
    """Bundled output of ``suggest_consumptions``."""

    target_quantity: float
    target_quantity_unit: str
    rows: list[SuggestedConsumption]
    warnings: list[str]


# ── Helpers ────────────────────────────────────────────────────────


def _is_volumetric_unit(unit: str) -> bool:
    return unit in ("mL", "L")


def _normalize_to_mL(qty: float, unit: str) -> float:
    """Convert a volumetric quantity to mL. Pass-through if not vol."""
    if unit == "L":
        return qty * 1000.0
    return qty


def _normalize_to_g(qty: float, unit: str) -> float:
    if unit == "kg":
        return qty * 1000.0
    return qty


def _candidate_lots(substance_id: int, want_unit: str) -> list[InventoryItem]:
    """Active lots usable as a source of ``substance_id``.

    Two kinds of lots qualify:

    * **Pure substance lots** (``InventoryItem.substance_id == substance_id``)
      — straightforward: a bottle of HCl gas, a bottle of distilled
      water, a bag of NaCl.
    * **Mixture lots whose primary solute is the substance**
      (``InventoryItem.mixture.components`` contains a ``solute``
      component pointing at ``substance_id``). This is essential for
      dilution preparations: to make HCl 6N from HCl 12N we draw
      from a *mixture* lot of HCl 12N, not from a pure-HCl lot
      (which would be the gas form, often impractical).

    Sorted most-recent first; only lots with positive remaining
    quantity in the relevant unit category are returned.
    """
    from stoic_eln.models.mixture import (
        COMPONENT_ROLE_SOLUTE,
    )

    # 1. Pure substance lots
    direct = db.session.query(InventoryItem).filter(
        InventoryItem.substance_id == substance_id,
        InventoryItem.is_active.is_(True),
    )

    # 2. Mixture lots where the substance appears as a solute
    via_mixture = (
        db.session.query(InventoryItem)
        .join(MixtureComponent, MixtureComponent.mixture_id == InventoryItem.mixture_id)
        .filter(
            InventoryItem.is_active.is_(True),
            MixtureComponent.substance_id == substance_id,
            MixtureComponent.role == COMPONENT_ROLE_SOLUTE,
        )
    )

    rows = direct.union(via_mixture).all()

    # Filter empty-on-this-axis lots and sort most-recent first.
    if _is_volumetric_unit(want_unit):
        rows = [r for r in rows if r.quantity_mL and r.quantity_mL > 0]
    else:
        rows = [r for r in rows if r.quantity_g and r.quantity_g > 0]

    # Sort most-recent purchase first. Lots with purchased_at=None
    # (never set by the operator) sink to the bottom — treated as
    # "unknown purchase date". Using ``date.min`` as the fallback
    # avoids the ``TypeError: can't compare datetime.datetime to
    # datetime.date`` that would arise from mixing the two types
    # (purchased_at is a Date column, created_at is a DateTime).
    rows.sort(
        key=lambda r: (
            r.purchased_at or date.min,
            r.id,
        ),
        reverse=True,
    )
    return rows


def _candidate_lots_for_mixture(
    mixture_id: int,
    want_unit: str,
) -> list[InventoryItem]:
    """Active lots OF a specific mixture (not "containing" — being).

    Used when a recipe component points at a ``child_mixture`` rather
    than a pure substance — e.g. the solute of "HCl 6N" is HCl 12N,
    and we need to draw from an existing physical lot of HCl 12N.

    Unlike :func:`_candidate_lots`, this does NOT chase across the
    hierarchy. By design (decision: cascade is 1-level) the system
    consumes the directly-named precursor lot and stops there — the
    parent mixture's own ancestry was already settled at the time
    that lot was prepared.

    Sorted most-recent first; only lots with positive remaining
    quantity in the relevant unit category are returned.
    """
    rows = (
        db.session.query(InventoryItem)
        .filter(
            InventoryItem.mixture_id == mixture_id,
            InventoryItem.is_active.is_(True),
        )
        .all()
    )

    if _is_volumetric_unit(want_unit):
        rows = [r for r in rows if r.quantity_mL and r.quantity_mL > 0]
    else:
        rows = [r for r in rows if r.quantity_g and r.quantity_g > 0]

    # See _candidate_lots: same rationale for the sort key.
    rows.sort(
        key=lambda r: (
            r.purchased_at or date.min,
            r.id,
        ),
        reverse=True,
    )
    return rows


def _candidates_for_component(
    comp: MixtureComponent,
    want_unit: str,
) -> list[InventoryItem]:
    """Dispatcher: route candidate lookup based on component kind.

    A ``MixtureComponent`` has a strict XOR between ``substance_id``
    and ``child_mixture_id`` — exactly one is set. This helper picks
    the right backing query so the rest of ``suggest_consumptions``
    can treat both cases uniformly.
    """
    if comp.is_mixture_component:
        return _candidate_lots_for_mixture(comp.child_mixture_id, want_unit)
    if comp.substance_id is not None:
        return _candidate_lots(comp.substance_id, want_unit)
    # Should never happen (XOR constraint guarantees one is set), but
    # defensive: return empty list rather than raise from a query helper.
    return []


def _lot_summary(lot: InventoryItem, want_unit: str) -> LotSummary:
    if _is_volumetric_unit(want_unit):
        q = lot.quantity_mL or 0.0
        u = "mL"
    else:
        q = lot.quantity_g or 0.0
        u = "g"
    return LotSummary(
        id=lot.id,
        batch_code=lot.batch_code or f"#{lot.id}",
        quantity_remaining=q,
        quantity_unit=u,
        expiry_date=lot.expiry_date.isoformat() if lot.expiry_date else None,
        location=lot.location,
    )


# ── Concentration unit groups ───────────────────────────────────────
#
# A dilution makes sense only when stock and target concentrations
# are in compatible units. "12 N → 6 N" is fine; "12 N → 50 %v/v" is
# nonsense (the conversion needs molecular weight + density we don't
# know). We group units by the kind of quantity they express:
#
#   * normality   — N
#   * molarity    — M, mM (mM scales to M by /1000)
#   * volume %    — %v/v
#   * mass %      — %w/w
#   * mass-vol %  — %w/v
#   * mass/vol    — mg/mL, g/L (both express g per L; mg/mL → g/L by ×1)
#   * mass-fract. — ppm
#   * ratio       — bare ratio numbers ("parts of")
#
# Two units are dilution-compatible iff they sit in the same group.
# Within a group, we apply a scaling factor to bring both sides to a
# canonical unit before applying C₁V₁ = C₂V₂.

UNIT_GROUPS: dict[str, str] = {
    "N": "normality",
    "M": "molarity",
    "mM": "molarity",
    "%v/v": "vol_pct",
    "%w/w": "mass_pct",
    "%w/v": "mass_vol_pct",
    "mg/mL": "mass_per_vol",
    "g/L": "mass_per_vol",
    "ppm": "ppm",
    "ratio": "ratio",
}

# Scale to a canonical reference within each group, so the dilution
# ratio works regardless of the user's chosen units.
#   For molarity:    M is canonical, mM = 0.001 × M.
#   For mass/vol:    g/L is canonical, mg/mL = 1.0 × g/L
#                    (because 1 mg/mL = 1 g/L by mass density).
#   Other groups have a single canonical unit each.
_UNIT_TO_CANONICAL: dict[str, float] = {
    "N": 1.0,
    "M": 1.0,
    "mM": 0.001,
    "%v/v": 1.0,
    "%w/w": 1.0,
    "%w/v": 1.0,
    "mg/mL": 1.0,
    "g/L": 1.0,
    "ppm": 1.0,
    "ratio": 1.0,
}


def _normalize_concentration(value: float, unit: str) -> float | None:
    """Convert ``value`` to its group's canonical unit, or return None
    if the unit is unknown.

    Used by the dilution-ratio math so 12 N / 6 N and 12000 mM / 6 M
    both produce the same 0.5 ratio.
    """
    if unit not in UNIT_GROUPS:
        return None
    return value * _UNIT_TO_CANONICAL[unit]


def _are_dilution_compatible(unit_stock: str, unit_target: str) -> bool:
    """True iff ``unit_stock`` and ``unit_target`` are in the same
    dilution-compatible group.
    """
    if unit_stock not in UNIT_GROUPS or unit_target not in UNIT_GROUPS:
        return False
    return UNIT_GROUPS[unit_stock] == UNIT_GROUPS[unit_target]


# ── Stock concentration reading ─────────────────────────────────────


@dataclass
class StockInfo:
    """How the system "sees" a precursor lot's concentration.

    ``concentration`` is None when the lot has no concentration
    information (e.g. a pure substance lot: we treat that as "pure"
    in the context of dilution math, conceptually 100% for the %
    groups or "stock = target" for others — see ``read_stock_for_solute``).

    ``source`` describes WHERE the value came from, for showing to
    the operator in the UI so they aren't surprised by the number.
    Values: "lot_mixture" (from lot.mixture.primary_concentration),
    "lot_component" (from MixtureComponent on the lot's mixture),
    "pure_substance" (a substance lot, assumed 100% for % units),
    "missing".
    """

    concentration: float | None
    unit: str | None
    source: str
    display_text: str  # something to surface in the UI, e.g. "12 N (HCl 12N)"


def read_stock_for_solute(
    lot: InventoryItem,
    solute_substance_id: int,
) -> StockInfo:
    """Read the precursor lot's stock concentration for a given solute.

    Two cases:

    1. **Mixture lot** (``lot.mixture_id`` set). The stock concentration
       comes from:
         - the matching ``MixtureComponent`` of the lot's mixture
           where ``substance_id == solute_substance_id`` and the
           concentration is populated, OR
         - the mixture's ``primary_concentration`` when the solute
           IS the primary one and the per-component value is absent.
       The first hit wins.

    2. **Pure substance lot** (``lot.substance_id`` set). We don't
       know the concentration — strictly speaking a pure substance
       is "100% of itself", but for dilution math we need to know
       in what unit. We return ``unit=None`` and a marker source,
       and the caller decides what to do (typically: skip the
       dilution strategy and fall back to a 1:1 transfer).
    """
    if lot.mixture is not None:
        mixture = lot.mixture
        # Per-component match
        for comp in mixture.components:
            if (
                comp.substance_id == solute_substance_id
                and comp.concentration is not None
                and comp.concentration_unit
            ):
                return StockInfo(
                    concentration=comp.concentration,
                    unit=comp.concentration_unit,
                    source="lot_component",
                    display_text=(
                        f"{comp.concentration:g} {comp.concentration_unit} ({mixture.name})"
                    ),
                )
        # Mixture's primary concentration (only if the solute matches
        # at least one of the mixture's solute components — sanity
        # check, otherwise an HCl 12N lot wouldn't be reported as
        # "12 N" when asked about an unrelated solute).
        solute_components = [
            c
            for c in mixture.components
            if c.role == COMPONENT_ROLE_SOLUTE and c.substance_id == solute_substance_id
        ]
        if (
            solute_components
            and mixture.primary_concentration is not None
            and mixture.primary_concentration_unit
        ):
            return StockInfo(
                concentration=mixture.primary_concentration,
                unit=mixture.primary_concentration_unit,
                source="lot_mixture",
                display_text=(
                    f"{mixture.primary_concentration:g} "
                    f"{mixture.primary_concentration_unit} "
                    f"({mixture.name})"
                ),
            )
        # Mixture lot whose composition doesn't yield a known
        # concentration for this solute — uncommon but possible
        # (e.g. an old "quick-label" mixture with no structured
        # components).
        return StockInfo(
            concentration=None,
            unit=None,
            source="missing",
            display_text=f"concentrazione sconosciuta ({mixture.name})",
        )

    # Pure substance lot
    if lot.substance is not None:
        return StockInfo(
            concentration=None,  # caller treats as "use as-is" / 100%
            unit=None,
            source="pure_substance",
            display_text=f"sostanza pura ({lot.substance.name})",
        )

    return StockInfo(
        concentration=None,
        unit=None,
        source="missing",
        display_text="—",
    )


def read_stock_for_child_mixture(
    lot: InventoryItem,
    child_mixture: Mixture,
) -> StockInfo:
    """Read the stock concentration when the recipe's solute is
    itself a child_mixture (not a pure substance).

    Example: preparing HCl 6N where the solute component is the
    child_mixture "HCl 12N". We need to know "12 N" to compute the
    dilution. By design decision (see PATCH-NOTES), we read this
    directly from ``child_mixture.primary_concentration`` — no
    fallback chain through inner components. If the child_mixture
    has no primary concentration set, that's a configuration error
    in the catalog and the operator must fix it; we surface a
    ``missing`` StockInfo so the auto-suggest gracefully degrades.

    The ``lot`` parameter is the proposed precursor lot. It is
    expected to be a lot of ``child_mixture`` (``lot.mixture_id ==
    child_mixture.id``); we don't enforce it here because the
    candidate selection upstream already guarantees this.
    """
    if child_mixture.primary_concentration is not None and child_mixture.primary_concentration_unit:
        return StockInfo(
            concentration=child_mixture.primary_concentration,
            unit=child_mixture.primary_concentration_unit,
            source="child_mixture_primary",
            display_text=(
                f"{child_mixture.primary_concentration:g} "
                f"{child_mixture.primary_concentration_unit} "
                f"({child_mixture.name})"
            ),
        )
    return StockInfo(
        concentration=None,
        unit=None,
        source="missing",
        display_text=f"concentrazione sconosciuta ({child_mixture.name})",
    )


# ── Auto-suggest ───────────────────────────────────────────────────


def suggest_consumptions(
    *,
    mixture: Mixture,
    target_quantity: float,
    target_unit: str,
) -> SuggestionResult:
    """Propose how to prepare ``target_quantity`` of ``mixture``.

    Strategy:
      * If the mixture has a primary concentration (e.g. HCl 6N) and
        a single solute component, propose
            V_solute_stock = V_target × C_target / C_solute_stock
        finding the most-recent active lot of the solute substance
        whose own primary concentration is known, then fill the
        remainder with the solvent.
      * Otherwise, if the mixture has %v/v cosolvent components
        summing to ~100, propose pro-rata splits.
      * Otherwise, return rows with zero quantities — the operator
        fills them in.

    Returns a :class:`SuggestionResult` carrying one row per recipe
    component plus any warnings about lots running low or
    concentrations missing.
    """
    rows: list[SuggestedConsumption] = []
    warnings: list[str] = []

    if not mixture.components:
        # Quick-label mixture with no recipe: nothing to suggest.
        warnings.append(
            "This mixture has no defined components. "
            "Add components to use the automatic suggestion."
        )
        return SuggestionResult(
            target_quantity=target_quantity,
            target_quantity_unit=target_unit,
            rows=[],
            warnings=warnings,
        )

    # Pre-compute candidates per component so we don't re-query.
    candidates_per_comp: dict[int, list[InventoryItem]] = {}
    for comp in mixture.components:
        candidates_per_comp[comp.id] = _candidates_for_component(comp, target_unit)

    # Strategy detection.
    #
    # We classify the recipe into one of three buckets:
    #
    #   - **single_solute_dilution**: exactly one solute component +
    #     target has a primary concentration. The stock concentration
    #     is read AT SUGGEST TIME from the proposed precursor lot
    #     (not from the recipe's MixtureComponent — that's only a
    #     fallback hint). This is the dynamic behaviour the operator
    #     asked for: pick a different precursor lot and the math
    #     updates accordingly. The units of stock and target must be
    #     dilution-compatible (same UNIT_GROUPS group).
    #
    #   - **ratio_parts**: at least one non-solvent component carries
    #     ``unit="ratio"`` with a numeric value (e.g. EtOAc 5, PE 2,
    #     meaning 5:2). We compute the share of the total as
    #     ``parts / sum(parts)`` and apply to the target volume.
    #     Components with non-ratio units in the same recipe (a
    #     ratio mixture with one component explicitly in %v/v) are
    #     left as-is and reported in warnings.
    #
    #   - **cosolvent_pct**: every percentage-coded component sums
    #     to ~100 — the classic eluent at 95:5 expressed as %v/v.
    #     A single global rule: each component's share = its pct/100.
    #
    #   - **fallback**: no strategy applies; emit zero quantities and
    #     a warning so the operator fills them in by hand.

    solutes = [c for c in mixture.components if c.role == COMPONENT_ROLE_SOLUTE]
    mass_conc_solutes = [
        c
        for c in solutes
        if c.concentration_unit in ("g/L", "mg/mL") and c.concentration is not None
    ]
    ratio_components = [
        c
        for c in mixture.components
        if c.concentration_unit == "ratio" and c.concentration is not None
    ]
    pct_components = [
        c
        for c in mixture.components
        if c.concentration_unit in ("%v/v", "%w/w", "%w/v") and c.concentration is not None
    ]
    pct_total = sum(c.concentration for c in pct_components)

    # Detect dilution applicability: needs primary target concentration
    # and exactly one solute. We DON'T validate stock concentration
    # here — we'll read that from the proposed precursor lot below
    # and fall back gracefully if it's missing/incompatible.
    can_try_dilution = (
        len(solutes) == 1
        and mixture.primary_concentration is not None
        and mixture.primary_concentration > 0
        and mixture.primary_concentration_unit
    )

    strategy = "fallback"
    if can_try_dilution:
        strategy = "single_solute_dilution"
    elif mass_conc_solutes:
        strategy = "mass_concentration"
    elif ratio_components and len(ratio_components) >= 2:
        strategy = "ratio_parts"
    elif pct_components and 99.0 <= pct_total <= 101.0:
        strategy = "cosolvent_pct"

    # For ratio strategy: total parts and per-component shares
    ratio_total_parts = sum(c.concentration for c in ratio_components)

    # For dilution strategy: read stock concentration from the
    # SUGGESTED precursor lot (the most-recent active lot of the
    # solute substance). The math:
    #   V_stock = V_target × C_target_canonical / C_stock_canonical
    # where both Cs are first normalized to their group's canonical
    # unit so 12 mM target / 6 M stock works as expected.
    solute_volume_target_mL = 0.0  # filled below if dilution applies
    dilution_stock_info: StockInfo | None = None
    if strategy == "single_solute_dilution":
        solute_comp = solutes[0]
        solute_lots = candidates_per_comp.get(solute_comp.id, [])
        if solute_lots:
            # The stock-reading path depends on whether the solute is
            # a pure substance or a child_mixture in the recipe.
            if solute_comp.is_mixture_component:
                stock_info = read_stock_for_child_mixture(
                    solute_lots[0],
                    solute_comp.child_mixture,
                )
            else:
                stock_info = read_stock_for_solute(
                    solute_lots[0],
                    solute_comp.substance_id,
                )
            dilution_stock_info = stock_info
            # Three sub-cases for the stock value:
            #   a) Mixture lot with known concentration in a compatible
            #      unit → real dilution math.
            #   b) Pure substance lot → we don't have a concentration,
            #      but the convention "1:1 of pure substance into the
            #      target concentration" only makes physical sense
            #      when target_unit is mass (g, kg) — for solutions
            #      this is unusual. We fall back to using the recipe
            #      hint (solute_comp.concentration) if present, else
            #      fallback strategy.
            #   c) Mixture lot with unknown / incompatible unit:
            #      degrade to recipe hint, else fallback.
            stock_value = stock_info.concentration
            stock_unit = stock_info.unit

            # If lot didn't give us a concentration, fall back to
            # what the recipe's solute component says.
            if (
                stock_value is None
                and solute_comp.concentration is not None
                and solute_comp.concentration_unit
            ):
                stock_value = solute_comp.concentration
                stock_unit = solute_comp.concentration_unit

            if (
                stock_value is not None
                and stock_unit
                and _are_dilution_compatible(
                    stock_unit,
                    mixture.primary_concentration_unit,
                )
            ):
                c_target = _normalize_concentration(
                    mixture.primary_concentration,
                    mixture.primary_concentration_unit,
                )
                c_stock = _normalize_concentration(stock_value, stock_unit)
                if c_target is not None and c_stock and c_stock > 0:
                    ratio = c_target / c_stock
                    v_target = _normalize_to_mL(target_quantity, target_unit)
                    solute_volume_target_mL = v_target * ratio
            else:
                # Strategy can't proceed for this recipe — surface a
                # warning so the operator knows the auto-suggest is
                # leaving the row blank.
                if stock_value is None:
                    warnings.append(
                        f"Stock concentration of "
                        f"{solute_comp.display_name} cannot be determined "
                        "from the suggested lot; fill in manually."
                    )
                else:
                    warnings.append(
                        f"Stock unit ({stock_unit}) and target "
                        f"({mixture.primary_concentration_unit}) "
                        "are incompatible for dilution."
                    )
                strategy = "fallback"

    # Now build a row per recipe component.
    for comp in mixture.components:
        cands = candidates_per_comp[comp.id]
        suggested_lot = cands[0] if cands else None

        suggested_qty: float | None = None
        suggested_unit_out: str | None = target_unit if _is_volumetric_unit(target_unit) else "g"
        row_stock_info: StockInfo | None = None

        if strategy == "single_solute_dilution":
            v_target_mL = _normalize_to_mL(target_quantity, target_unit)
            if comp.role == COMPONENT_ROLE_SOLUTE:
                qty_mL = solute_volume_target_mL
                row_stock_info = dilution_stock_info
            else:
                qty_mL = max(0.0, v_target_mL - solute_volume_target_mL)
            if target_unit == "L":
                suggested_qty = qty_mL / 1000.0
                suggested_unit_out = "L"
            else:
                suggested_qty = qty_mL
                suggested_unit_out = "mL"

        elif strategy == "ratio_parts":
            if (
                comp.concentration_unit == "ratio"
                and comp.concentration is not None
                and ratio_total_parts > 0
            ):
                v_target = _normalize_to_mL(target_quantity, target_unit)
                qty_mL = v_target * (comp.concentration / ratio_total_parts)
                if target_unit == "L":
                    suggested_qty = qty_mL / 1000.0
                    suggested_unit_out = "L"
                else:
                    suggested_qty = qty_mL
                    suggested_unit_out = "mL"

        elif strategy == "mass_concentration":
            # Solutes: mass = concentration_g_per_L × volume_target_L
            # Solvents with no concentration: fill to target volume (qsp)
            v_target_L = _normalize_to_mL(target_quantity, target_unit) / 1000.0
            if comp.concentration_unit in ("g/L", "mg/mL") and comp.concentration is not None:
                # g/L and mg/mL are both 1:1 in g/L (per _UNIT_TO_CANONICAL)
                conc_g_per_L = comp.concentration * _UNIT_TO_CANONICAL.get(
                    comp.concentration_unit, 1.0
                )
                suggested_qty = conc_g_per_L * v_target_L
                suggested_unit_out = "g"
            elif comp.role == COMPONENT_ROLE_SOLVENT and (
                comp.concentration is None or comp.concentration_unit is None
            ):
                # Solvent: propose "fill to volume" (qsp)
                if target_unit == "L":
                    suggested_qty = target_quantity
                    suggested_unit_out = "L"
                else:
                    suggested_qty = _normalize_to_mL(target_quantity, target_unit)
                    suggested_unit_out = "mL"

        elif strategy == "cosolvent_pct":
            if comp.concentration_unit in ("%v/v", "%w/w", "%w/v") and comp.concentration:
                v_target = _normalize_to_mL(target_quantity, target_unit)
                qty_mL = v_target * (comp.concentration / 100.0)
                if target_unit == "L":
                    suggested_qty = qty_mL / 1000.0
                    suggested_unit_out = "L"
                else:
                    suggested_qty = qty_mL
                    suggested_unit_out = "mL"

        # Sanity check: warn if the suggested quantity exceeds what's
        # available on the suggested lot.
        if suggested_qty is not None and suggested_lot is not None:
            if _is_volumetric_unit(suggested_unit_out or ""):
                have_in_native = suggested_lot.quantity_mL or 0.0
                need_in_native = _normalize_to_mL(
                    suggested_qty,
                    suggested_unit_out or "mL",
                )
            else:
                have_in_native = suggested_lot.quantity_g or 0.0
                need_in_native = _normalize_to_g(
                    suggested_qty,
                    suggested_unit_out or "g",
                )
            if need_in_native > have_in_native:
                warnings.append(
                    f"Lotto {suggested_lot.batch_code or '#' + str(suggested_lot.id)} "
                    f"di {comp.display_name}: solo {have_in_native:g} "
                    f"{suggested_unit_out} disponibili, "
                    f"ne servirebbero {need_in_native:g}."
                )

        if suggested_lot is None:
            warnings.append(f"Nessun lotto attivo trovato per {comp.display_name}.")

        rows.append(
            SuggestedConsumption(
                component_id=comp.id,
                substance_id=comp.substance_id,
                mixture_id=comp.child_mixture_id,
                display_name=comp.display_name,
                role=comp.role,
                suggested_lot_id=suggested_lot.id if suggested_lot else None,
                suggested_quantity=suggested_qty,
                suggested_unit=suggested_unit_out,
                available_lots=[_lot_summary(l, target_unit) for l in cands],
                stock_info=row_stock_info,
            )
        )

    if strategy == "fallback":
        warnings.append(
            "Missing or incompatible concentrations: "
            "automatic suggestion cannot propose quantities. Fill in manually."
        )

    return SuggestionResult(
        target_quantity=target_quantity,
        target_quantity_unit=target_unit,
        rows=rows,
        warnings=warnings,
    )


# ── Execution ──────────────────────────────────────────────────────


@dataclass
class ConsumptionInput:
    """One operator-confirmed consumption line submitted from the form."""

    inventory_item_id: int
    quantity_consumed: float
    quantity_unit: str  # mL/L/g/kg
    notes: str | None = None


@dataclass
class PrepInput:
    """Full operator-confirmed input to ``execute_preparation``."""

    mixture_id: int
    target_quantity: float
    target_quantity_unit: str
    consumptions: list[ConsumptionInput]
    output_batch_code: str | None  # if None, will be auto-generated
    output_location: str | None
    output_expiry_date: str | None  # ISO date string
    output_notes: str | None
    prepared_by_id: int | None


def execute_preparation(
    inp: PrepInput,
) -> MixturePrep:
    """Run a preparation transactionally.

    Steps:
      1. Validate mixture exists and is active.
      2. Validate every consumption: lot exists, is active, has
         enough remaining quantity in the requested unit.
      3. Decrement precursor lots' quantity_g / quantity_mL.
      4. Auto-generate batch code if ``output_batch_code`` is None.
      5. Create the output InventoryItem (lot of the target mixture).
      6. Create the MixturePrep + MixturePrepConsumption rows.
      7. Commit. On any failure, rolls back and raises.

    Returns the persisted MixturePrep with ``output_lot`` populated.

    Raises:
      ValueError: validation failures (lot not found, not enough
        quantity, mixture inactive). The DB is not modified.
    """
    mixture = db.session.get(Mixture, inp.mixture_id)
    if mixture is None:
        raise ValueError("Mixture not found.")
    if not mixture.is_active:
        raise ValueError("Mixture is inactive and cannot be prepared.")

    if inp.target_quantity_unit not in ("mL", "L", "g", "kg"):
        raise ValueError(f"Unsupported target unit: {inp.target_quantity_unit!r}")
    if inp.target_quantity <= 0:
        raise ValueError("Target quantity must be positive.")

    # Resolve every consumption lot before mutating anything.
    resolved: list[tuple[InventoryItem, float, str, str | None]] = []
    for c in inp.consumptions:
        lot = db.session.get(InventoryItem, c.inventory_item_id)
        if lot is None:
            raise ValueError(f"Lot #{c.inventory_item_id} not found.")
        if not lot.is_active:
            raise ValueError(f"Lot {lot.batch_code or lot.id} is inactive and cannot be used.")
        if c.quantity_unit not in ("mL", "L", "g", "kg"):
            raise ValueError(f"Unsupported consumption unit: {c.quantity_unit!r}")
        if c.quantity_consumed <= 0:
            # zero is a sign of "skip this row"; let the caller filter
            # those out before calling. We treat negative as a hard error.
            raise ValueError(f"Non-positive quantity consumed for lot {lot.batch_code or lot.id}.")
        resolved.append((lot, c.quantity_consumed, c.quantity_unit, c.notes))

    # Validate availability + apply decrements.
    for lot, qty, unit, _notes in resolved:
        if unit in ("mL", "L"):
            need = _normalize_to_mL(qty, unit)
            have = lot.quantity_mL or 0.0
            if need > have:
                raise ValueError(
                    f"Lotto {lot.batch_code or lot.id}: "
                    f"servono {need:g} mL, disponibili {have:g} mL."
                )
            lot.quantity_mL = have - need
        else:
            need = _normalize_to_g(qty, unit)
            have = lot.quantity_g or 0.0
            if need > have:
                raise ValueError(
                    f"Lotto {lot.batch_code or lot.id}: servono {need:g} g, disponibili {have:g} g."
                )
            lot.quantity_g = have - need

    # Generate batch code if not provided.
    if inp.output_batch_code:
        output_code = inp.output_batch_code
        # We still need a sequence number for MixturePrep.sequence
        # even when the user gave a custom code — keep it consistent
        # with auto-generated runs.
        from stoic_eln.services.prep_code import (
            get_scope,
            next_sequence_number,
        )

        seq = next_sequence_number(
            scope=get_scope(),
            mixture_id=mixture.id,
            year=datetime.now(UTC).year,
        )
    else:
        from stoic_eln.services.prep_code import generate_prep_code

        output_code, seq = generate_prep_code(
            mixture_name=mixture.name,
            mixture_id=mixture.id,
        )

    # Create the output lot. Quantity stored in the unit category
    # (mass vs volume) matching target_quantity_unit.
    output_lot = InventoryItem(
        mixture_id=mixture.id,
        batch_code=output_code,
        location=inp.output_location,
        notes=inp.output_notes,
        is_active=True,
    )
    if inp.target_quantity_unit in ("mL", "L"):
        v = _normalize_to_mL(inp.target_quantity, inp.target_quantity_unit)
        output_lot.quantity_mL = v
        output_lot.initial_quantity_mL = v
    else:
        m = _normalize_to_g(inp.target_quantity, inp.target_quantity_unit)
        output_lot.quantity_g = m
        output_lot.initial_quantity_g = m

    # Pick the group from the first consumed lot — preserves
    # ownership semantics across the whole preparation.
    if resolved:
        output_lot.group_id = resolved[0][0].group_id

    # Production cost of the mixture: sum the cost of the priced
    # precursor lots consumed (consumed quantity × the lot's €/unit).
    # A precursor without a price is skipped; the total is set as long
    # as at least one precursor was priced — partial costs are still
    # useful, and this lets runs that consume the mixture count it.
    from stoic_eln.services.run_cost import _line_cost

    cost_total = 0.0
    any_priced = False
    for c_lot, c_qty, c_unit, _cn in resolved:
        if c_unit in ("mL", "L"):
            line = _line_cost(None, _normalize_to_mL(c_qty, c_unit), c_lot)
        else:
            line = _line_cost(_normalize_to_g(c_qty, c_unit), None, c_lot)
        if line is not None:
            cost_total += line
            any_priced = True
    if any_priced:
        output_lot.total_cost_eur = cost_total

    # Expiry date for the output lot:
    #   - explicit user input wins (operator override)
    #   - otherwise default to the earliest expiry among the
    #     consumed precursor lots — the produced mixture can't
    #     reasonably outlive its shortest-lived input
    #     (e.g. EtOAc/PE 5:3 expires when EtOAc expires)
    #
    # If no precursor has an expiry_date, leave it unset rather
    # than guessing — the operator can fill it in later.
    if inp.output_expiry_date:
        from datetime import date as _date

        try:
            output_lot.expiry_date = _date.fromisoformat(inp.output_expiry_date)
        except ValueError:
            # Bad date — silently ignore rather than aborting the
            # whole preparation. The operator can edit afterwards.
            pass
    else:
        precursor_expiries = [
            lot.expiry_date for lot, _q, _u, _n in resolved if lot.expiry_date is not None
        ]
        if precursor_expiries:
            output_lot.expiry_date = min(precursor_expiries)

    db.session.add(output_lot)
    db.session.flush()  # populate output_lot.id

    # Create the MixturePrep header.
    prep = MixturePrep(
        code=output_code,
        sequence=seq,
        year=datetime.now(UTC).year,
        mixture_id=mixture.id,
        target_quantity=inp.target_quantity,
        target_quantity_unit=inp.target_quantity_unit,
        output_inventory_item_id=output_lot.id,
        prepared_by_id=inp.prepared_by_id,
        notes=inp.output_notes,
    )
    db.session.add(prep)
    db.session.flush()

    # Wire the output lot to the prep via source_run_id-style
    # provenance — our InventoryItem already has source_run_id, but
    # it's tied to Run. We keep the link in MixturePrep itself
    # (output_inventory_item_id), so a query "which prep produced
    # this lot?" is just MixturePrep.query.filter_by(output_inventory_item_id=...).

    # Create consumption rows.
    for i, (lot, qty, unit, notes) in enumerate(resolved):
        db.session.add(
            MixturePrepConsumption(
                prep_id=prep.id,
                inventory_item_id=lot.id,
                quantity_consumed=qty,
                quantity_unit=unit,
                position=i,
                notes=notes,
            )
        )

    db.session.commit()
    return prep
# Wed  1 Jul 2026 05:59:28 CEST

