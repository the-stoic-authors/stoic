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
from datetime import datetime, UTC

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.mixture import (
    COMPONENT_ROLE_SOLUTE,
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
    """One row in the auto-suggest output: which lot, how much."""

    component_id: int  # MixtureComponent.id from the recipe
    substance_id: int  # for display
    substance_name: str
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

    rows.sort(
        key=lambda r: (
            r.purchased_at or r.created_at,
            r.id,
        ),
        reverse=True,
    )
    return rows


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
            "Questa miscela non ha componenti definiti. "
            "Aggiungi i componenti per usare il suggerimento automatico."
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
        candidates_per_comp[comp.id] = _candidate_lots(
            comp.substance_id,
            target_unit,
        )

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
                        f"Concentrazione stock di "
                        f"{solute_comp.substance.name} non determinabile "
                        "dal lotto suggerito; compila a mano."
                    )
                else:
                    warnings.append(
                        f"Unità stock ({stock_unit}) e target "
                        f"({mixture.primary_concentration_unit}) "
                        "incompatibili per diluizione."
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
                    f"di {comp.substance.name}: solo {have_in_native:g} "
                    f"{suggested_unit_out} disponibili, "
                    f"ne servirebbero {need_in_native:g}."
                )

        if suggested_lot is None:
            warnings.append(f"Nessun lotto attivo trovato per {comp.substance.name}.")

        rows.append(
            SuggestedConsumption(
                component_id=comp.id,
                substance_id=comp.substance_id,
                substance_name=comp.substance.name,
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
            "Concentrazioni mancanti o non confrontabili: il suggerimento "
            "automatico non può proporre quantità. Compila a mano."
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
        raise ValueError("Miscela non trovata.")
    if not mixture.is_active:
        raise ValueError("Miscela disattivata: non è preparabile.")

    if inp.target_quantity_unit not in ("mL", "L", "g", "kg"):
        raise ValueError(f"Unità target non supportata: {inp.target_quantity_unit!r}")
    if inp.target_quantity <= 0:
        raise ValueError("La quantità target deve essere positiva.")

    # Resolve every consumption lot before mutating anything.
    resolved: list[tuple[InventoryItem, float, str, str | None]] = []
    for c in inp.consumptions:
        lot = db.session.get(InventoryItem, c.inventory_item_id)
        if lot is None:
            raise ValueError(f"Lotto #{c.inventory_item_id} non trovato.")
        if not lot.is_active:
            raise ValueError(f"Lotto {lot.batch_code or lot.id} disattivato; non utilizzabile.")
        if c.quantity_unit not in ("mL", "L", "g", "kg"):
            raise ValueError(f"Unità di consumo non supportata: {c.quantity_unit!r}")
        if c.quantity_consumed <= 0:
            # zero is a sign of "skip this row"; let the caller filter
            # those out before calling. We treat negative as a hard error.
            raise ValueError(
                f"Quantità consumata non positiva per lotto {lot.batch_code or lot.id}."
            )
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
