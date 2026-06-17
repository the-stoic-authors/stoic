"""Stoic ELN — Seed data for the standard procedure library (P2b + P3).

Starter ``StepTemplate`` procedures every lab gets at first init.
They are ordinary library entries: fully editable and deletable. The
seeder (``seeds.loader.seed_procedures``) is idempotent by ``name``,
so a procedure a lab removes stays removed (seeds only run at
``flask init-db`` / ``scripts/init_db.py``, never on every boot).

Language: ENGLISH. Like the seeded substance catalogue, the procedure
library ships in one language; English reaches the widest audience for
an open-source product. A lab can rename/edit any entry.

Design notes
------------
* The three *flash* procedures encode silica:crude mass loading scaled
  by separation difficulty (ΔRf), as DATA not hardcoded logic. Silica
  uses the ``g_per_g`` ratio kind (grams of silica per gram of the step
  reference); set the step reference to the PRODUCT so it means "g per g
  of crude" (noted in each description).
* "Column Ø" is a free entry of kind ``column_diameter_mm``: its
  ``ratio_value`` is the bed height in cm; the suggested inner diameter
  is derived from the silica mass. Its role is NOT ``stationary_phase``
  so the diameter lookup picks the silica.
* Recrystallization and extraction use ad-lib (q.b./"as needed") volumes
  — generic versions have nothing computable; their value is the named
  structure + checklist. Guideline ratios live in the description.
* Distillation procedures declare recorded *parameters* (P3): head
  temperature range, and for the vacuum variant pressure + bath T. These
  are filled by the operator at run time and printed in the run PDF.

Each component dict supports:
    role, ratio_kind, ratio_value (optional),
    substance_inchikey (→ resolved to substance at seed time) OR
    free_name + free_unit (a non-inventory line).
A procedure may also declare ``parameters``: a list of {label, unit}.
"""

from __future__ import annotations

# InChIKeys of substances referenced by procedures (must exist in the
# substance seed catalogue — see seeds/substances.py).
_SILICA = "VYPSYNLAJGMNEJ-UHFFFAOYSA-N"  # Silica gel
_NA2SO4 = "PMZURENOXWZQFD-UHFFFAOYSA-L"  # Sodium sulfate (anhydrous)


def _flash(name: str, difficulty: str, silica_g_per_g: float, eluent: str) -> dict:
    return {
        "name": name,
        "kind": "purification",
        "description": (
            f"Flash chromatography — {difficulty} separation.\n"
            f"Silica ~{silica_g_per_g:g} g/g of crude · eluent {eluent} · "
            "bed height 15 cm.\n"
            "Set the step reference to the PRODUCT: the silica g/g and the "
            "column Ø are computed on the crude mass."
        ),
        "components": [
            {
                "role": "stationary_phase",
                "substance_inchikey": _SILICA,
                "ratio_kind": "g_per_g",
                "ratio_value": silica_g_per_g,
            },
            {
                "role": "additive",
                "free_name": "Column Ø",
                "free_unit": "mm",
                "ratio_kind": "column_diameter_mm",
                "ratio_value": 15.0,
            },
            {
                "role": "solvent",
                "free_name": "Eluent",
                "free_unit": "mL",
                "ratio_kind": "free",
            },
        ],
        "checklist": [
            "TLC the crude (estimate ΔRf, choose the eluent)",
            "Load dry or in the minimum volume of solvent",
            "Collect fractions and check them by TLC",
            "Combine the clean fractions and concentrate under reduced pressure",
        ],
    }


PROCEDURES: list[dict] = [
    _flash(
        "Flash chromatography — easy (ΔRf ≥ 0.3)",
        "easy (ΔRf ≥ 0.3)",
        30.0,
        "~150 mL/g (~10 CV)",
    ),
    _flash(
        "Flash chromatography — medium (ΔRf 0.15–0.3)",
        "medium (ΔRf 0.15–0.3)",
        50.0,
        "~250 mL/g (~16 CV)",
    ),
    _flash(
        "Flash chromatography — hard (ΔRf < 0.15)",
        "hard (ΔRf < 0.15)",
        100.0,
        "~500 mL/g (~30 CV)",
    ),
    {
        "name": "Standard extraction",
        "kind": "extraction",
        "description": (
            "Standard liquid-liquid extraction.\n"
            "Extract the aqueous phase 3× with equal volumes of organic "
            "solvent; wash the combined organics with sat. NaHCO₃ (if acids "
            "need neutralising), then brine; dry over Na₂SO₄ and filter.\n"
            "All volumes are as needed (depends on your separatory funnel)."
        ),
        "components": [
            {
                "role": "solvent",
                "free_name": "Extraction solvent (3×)",
                "free_unit": "mL",
                "ratio_kind": "free",
            },
            {
                "role": "base",
                "free_name": "Sat. aq. NaHCO₃",
                "free_unit": "mL",
                "ratio_kind": "free",
            },
            {
                "role": "solvent",
                "free_name": "Brine (sat. NaCl)",
                "free_unit": "mL",
                "ratio_kind": "free",
            },
            {
                "role": "additive",
                "substance_inchikey": _NA2SO4,
                "ratio_kind": "free",
            },
        ],
        "checklist": [
            "Transfer to a separatory funnel and separate the phases",
            "Extract the aqueous phase 3× with the solvent",
            "Wash the combined organics: sat. NaHCO₃ first, then brine",
            "Dry over Na₂SO₄ and filter",
            "Concentrate under reduced pressure",
        ],
    },
]


def _distillation(
    name: str,
    blurb: str,
    parameters: list[dict],
    checklist: list[str],
    with_boiling_chips: bool = True,
) -> dict:
    components = []
    if with_boiling_chips:
        components.append({"role": "additive", "free_name": "Boiling chips", "ratio_kind": "free"})
    return {
        "name": name,
        "kind": "purification",
        "description": blurb,
        "components": components,
        "parameters": parameters,
        "checklist": checklist,
    }


_T_HEAD = [
    {"label": "Head T start", "unit": "°C"},
    {"label": "Head T end", "unit": "°C"},
]


PROCEDURES += [
    {
        "name": "Recrystallization",
        "kind": "purification",
        "description": (
            "Recrystallization (single solvent).\n"
            "Dissolve the crude in the minimum volume of boiling solvent "
            "(rough guide ~10–20 mL/g, depends on solubility); if needed "
            "decolorize with activated charcoal and filter hot; cool slowly "
            "to r.t. then in an ice bath.\n"
            "Volumes as needed."
        ),
        "components": [
            {
                "role": "solvent",
                "free_name": "Crystallization solvent",
                "free_unit": "mL",
                "ratio_kind": "free",
            },
            {
                "role": "additive",
                "free_name": "Activated charcoal (decolorizing)",
                "ratio_kind": "free",
            },
            {
                "role": "solvent",
                "free_name": "Wash solvent (cold)",
                "free_unit": "mL",
                "ratio_kind": "free",
            },
        ],
        "checklist": [
            "Dissolve the crude in the minimum volume of boiling solvent",
            "If coloured: add activated charcoal and filter hot (Celite/cotton)",
            "Cool slowly to r.t., then in an ice bath (seed if needed)",
            "Filter the crystals under vacuum (Büchner)",
            "Wash with a little COLD solvent",
            "Dry; consider a 2nd crop from the mother liquor",
        ],
    },
    _distillation(
        "Simple distillation",
        (
            "Simple distillation at atmospheric pressure.\n"
            "For liquids with a large boiling-point difference "
            "(ΔTb > ~70 °C) from the impurities. Record the head-T range "
            "of the main fraction."
        ),
        _T_HEAD,
        [
            "Assemble the apparatus (flask, still head, thermometer at the side arm, condenser)",
            "Add boiling chips and heat gradually",
            "Discard the forerun (head)",
            "Collect the main fraction over the expected T range",
            "Stop before going to dryness",
        ],
    ),
    _distillation(
        "Fractional distillation",
        (
            "Fractional distillation at atmospheric pressure.\n"
            "Fractionating column to separate liquids with a small ΔTb. "
            "Control the reflux ratio; record the head-T range of each "
            "collected fraction."
        ),
        _T_HEAD,
        [
            "Assemble fractionating column + still head",
            "Bring to reflux and let the column stabilise",
            "Collect fractions while monitoring the head T",
            "TLC/GC the fractions if needed",
            "Stop before going to dryness",
        ],
    ),
    _distillation(
        "Vacuum distillation",
        (
            "Reduced-pressure distillation.\n"
            "For high-boiling or thermolabile compounds. Apply the vacuum "
            "BEFORE heating; record the pressure and the head-T range "
            "(the boiling temperature drops under vacuum)."
        ),
        [
            {"label": "Pressure", "unit": "mbar"},
            {"label": "Head T start", "unit": "°C"},
            {"label": "Head T end", "unit": "°C"},
            {"label": "Bath T", "unit": "°C"},
        ],
        [
            "Assemble the apparatus with cold trap(s) and vacuum source",
            "Apply the vacuum and check for leaks BEFORE heating",
            "Heat gradually (bath); note the pressure and head T",
            "Collect the main fraction",
            "Release the vacuum SLOWLY before turning off the bath",
        ],
        with_boiling_chips=False,
    ),
]
