"""Seed the database with 30 common laboratory substances.

Run with:
    .venv/bin/python scripts/seed_common_substances.py

What it does:
- Inserts ~30 substances common in a small organic chemistry lab
  (solvents, mineral acids/bases, drying agents, a few extras).
- Each entry includes name, IUPAC, CAS, formula, MW, SMILES, InChI,
  density (for liquids), state, MP/BP, and GHS pictograms + key
  H-phrases.
- ``is_solvent=True`` is set for substances normally used as solvents
  so they show up in solvent-pickers throughout the UI.
- Idempotent: for each entry, looks for a substance with matching
  ``cas_number``; if present, leaves it alone (won't overwrite
  manual edits the user made).

Data sources: PubChem, GESTIS, supplier SDS sheets (Sigma-Aldrich
and TCI). Curated to be conservative on hazards — when SDSs differ,
I picked the union of pictograms. Densities are at 20°C (most
common SDS reference).

Note on H/P phrases: I include only the headline hazard phrases
(generally the H3xx series — physical and health hazards). Full
SDS lists run 20+ phrases per substance; we're not reproducing
the SDS, just giving the user a sensible starting point they can
extend through PubChem-import if they want richer data.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the parent directory importable when running from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stoic_eln import create_app
from stoic_eln.extensions import db
from stoic_eln.models import Substance


# ─── The 30 substances ───────────────────────────────────────────


COMMON_SUBSTANCES: list[dict] = [
    # ── Halogenated solvents ───────────────────────────────────────
    {
        "name": "Diclorometano",
        "iupac_name": "dichloromethane",
        "cas_number": "75-09-2",
        "molecular_formula": "CH2Cl2",
        "molecular_weight": 84.93,
        "smiles": "ClCCl",
        "inchi": "InChI=1S/CH2Cl2/c2-1-3/h1H2",
        "inchi_key": "YMWUJEATGCHHMB-UHFFFAOYSA-N",
        "density": 1.325,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -97.0,
        "boiling_point_c": 39.6,
        "ghs_pictograms": ["GHS07", "GHS08"],
        "h_phrases": ["H315", "H319", "H335", "H336", "H351"],
        "p_phrases": ["P201", "P202", "P261", "P281", "P305+P351+P338"],
        "pubchem_cid": 6344,
    },
    {
        "name": "Cloroformio",
        "iupac_name": "trichloromethane",
        "cas_number": "67-66-3",
        "molecular_formula": "CHCl3",
        "molecular_weight": 119.38,
        "smiles": "C(Cl)(Cl)Cl",
        "inchi": "InChI=1S/CHCl3/c2-1(3)4/h1H",
        "inchi_key": "HEDRZPFGACZZDS-UHFFFAOYSA-N",
        "density": 1.489,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -63.5,
        "boiling_point_c": 61.2,
        "ghs_pictograms": ["GHS06", "GHS08"],
        "h_phrases": ["H302", "H315", "H319", "H331", "H336", "H351", "H361d", "H372"],
        "p_phrases": ["P201", "P260", "P273", "P301+P312", "P304+P340"],
        "pubchem_cid": 6212,
    },

    # ── Ether solvents ─────────────────────────────────────────────
    {
        "name": "Etere etilico",
        "iupac_name": "diethyl ether",
        "cas_number": "60-29-7",
        "molecular_formula": "C4H10O",
        "molecular_weight": 74.12,
        "smiles": "CCOCC",
        "inchi": "InChI=1S/C4H10O/c1-3-5-4-2/h3-4H2,1-2H3",
        "inchi_key": "RTZKZFJDLAIYFH-UHFFFAOYSA-N",
        "density": 0.713,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -116.3,
        "boiling_point_c": 34.6,
        "ghs_pictograms": ["GHS02", "GHS07"],
        "h_phrases": ["H224", "H302", "H336"],
        "p_phrases": ["P210", "P233", "P240", "P241", "P403+P235"],
        "pubchem_cid": 3283,
    },
    {
        "name": "Tetraidrofurano",
        "iupac_name": "tetrahydrofuran",
        "cas_number": "109-99-9",
        "molecular_formula": "C4H8O",
        "molecular_weight": 72.11,
        "smiles": "C1CCOC1",
        "inchi": "InChI=1S/C4H8O/c1-2-4-5-3-1/h1-4H2",
        "inchi_key": "WYURNTSHIVDZCO-UHFFFAOYSA-N",
        "density": 0.889,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -108.4,
        "boiling_point_c": 66.0,
        "ghs_pictograms": ["GHS02", "GHS07", "GHS08"],
        "h_phrases": ["H225", "H302", "H319", "H335", "H351"],
        "p_phrases": ["P201", "P210", "P233", "P280", "P305+P351+P338"],
        "pubchem_cid": 8028,
    },

    # ── Ester / ketone / aromatic / aliphatic solvents ────────────
    {
        "name": "Acetato di etile",
        "iupac_name": "ethyl acetate",
        "cas_number": "141-78-6",
        "molecular_formula": "C4H8O2",
        "molecular_weight": 88.11,
        "smiles": "CCOC(=O)C",
        "inchi": "InChI=1S/C4H8O2/c1-3-6-4(2)5/h3H2,1-2H3",
        "inchi_key": "XEKOWRVHYACXOJ-UHFFFAOYSA-N",
        "density": 0.902,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -83.6,
        "boiling_point_c": 77.1,
        "ghs_pictograms": ["GHS02", "GHS07"],
        "h_phrases": ["H225", "H319", "H336"],
        "p_phrases": ["P210", "P233", "P280", "P305+P351+P338"],
        "pubchem_cid": 8857,
    },
    {
        "name": "Acetone",
        "iupac_name": "propan-2-one",
        "cas_number": "67-64-1",
        "molecular_formula": "C3H6O",
        "molecular_weight": 58.08,
        "smiles": "CC(=O)C",
        "inchi": "InChI=1S/C3H6O/c1-3(2)4/h1-2H3",
        "inchi_key": "CSCPPACGZOOCGX-UHFFFAOYSA-N",
        "density": 0.791,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -94.9,
        "boiling_point_c": 56.1,
        "ghs_pictograms": ["GHS02", "GHS07"],
        "h_phrases": ["H225", "H319", "H336"],
        "p_phrases": ["P210", "P233", "P280", "P305+P351+P338"],
        "pubchem_cid": 180,
    },
    {
        "name": "Toluene",
        "iupac_name": "methylbenzene",
        "cas_number": "108-88-3",
        "molecular_formula": "C7H8",
        "molecular_weight": 92.14,
        "smiles": "Cc1ccccc1",
        "inchi": "InChI=1S/C7H8/c1-7-5-3-2-4-6-7/h2-6H,1H3",
        "inchi_key": "YXFVVABEGXRONW-UHFFFAOYSA-N",
        "density": 0.867,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -95.0,
        "boiling_point_c": 110.6,
        "ghs_pictograms": ["GHS02", "GHS07", "GHS08"],
        "h_phrases": ["H225", "H304", "H315", "H336", "H361d", "H373"],
        "p_phrases": ["P201", "P210", "P280", "P301+P310", "P331"],
        "pubchem_cid": 1140,
    },
    {
        "name": "Esano",
        "iupac_name": "n-hexane",
        "cas_number": "110-54-3",
        "molecular_formula": "C6H14",
        "molecular_weight": 86.18,
        "smiles": "CCCCCC",
        "inchi": "InChI=1S/C6H14/c1-3-5-6-4-2/h3-6H2,1-2H3",
        "inchi_key": "VLKZOEOYAKHREP-UHFFFAOYSA-N",
        "density": 0.655,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -95.3,
        "boiling_point_c": 68.7,
        "ghs_pictograms": ["GHS02", "GHS07", "GHS08", "GHS09"],
        "h_phrases": ["H225", "H304", "H315", "H336", "H361f", "H373", "H411"],
        "p_phrases": ["P201", "P210", "P273", "P301+P310", "P331"],
        "pubchem_cid": 8058,
    },
    {
        "name": "Etere di petrolio (40–60 °C)",
        "iupac_name": "petroleum ether",
        "cas_number": "8032-32-4",
        "molecular_formula": "CxHy",  # mixture
        "molecular_weight": None,
        "smiles": None,
        "inchi": None,
        "inchi_key": None,
        "density": 0.66,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": None,
        "boiling_point_c": 50.0,
        "ghs_pictograms": ["GHS02", "GHS07", "GHS08", "GHS09"],
        "h_phrases": ["H225", "H304", "H315", "H336", "H411"],
        "p_phrases": ["P210", "P273", "P301+P310", "P331"],
        "pubchem_cid": None,
        "notes": "Frazione 40–60 °C tipica per cromatografia. Composizione "
                 "variabile (alcani C5–C6).",
    },

    # ── Alcohol solvents ──────────────────────────────────────────
    {
        "name": "Metanolo",
        "iupac_name": "methanol",
        "cas_number": "67-56-1",
        "molecular_formula": "CH4O",
        "molecular_weight": 32.04,
        "smiles": "CO",
        "inchi": "InChI=1S/CH4O/c1-2/h2H,1H3",
        "inchi_key": "OKKJLVBELUTLKV-UHFFFAOYSA-N",
        "density": 0.792,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -97.6,
        "boiling_point_c": 64.7,
        "ghs_pictograms": ["GHS02", "GHS06", "GHS08"],
        "h_phrases": ["H225", "H301", "H311", "H331", "H370"],
        "p_phrases": ["P210", "P233", "P280", "P301+P310", "P304+P340"],
        "pubchem_cid": 887,
    },
    {
        "name": "Etanolo assoluto",
        "iupac_name": "ethanol",
        "cas_number": "64-17-5",
        "molecular_formula": "C2H6O",
        "molecular_weight": 46.07,
        "smiles": "CCO",
        "inchi": "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
        "inchi_key": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
        "density": 0.789,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -114.1,
        "boiling_point_c": 78.4,
        "ghs_pictograms": ["GHS02", "GHS07"],
        "h_phrases": ["H225", "H319"],
        "p_phrases": ["P210", "P233", "P280", "P305+P351+P338"],
        "pubchem_cid": 702,
    },
    {
        "name": "Isopropanolo",
        "iupac_name": "propan-2-ol",
        "cas_number": "67-63-0",
        "molecular_formula": "C3H8O",
        "molecular_weight": 60.10,
        "smiles": "CC(C)O",
        "inchi": "InChI=1S/C3H8O/c1-3(2)4/h3-4H,1-2H3",
        "inchi_key": "KFZMGEQAYNKOFK-UHFFFAOYSA-N",
        "density": 0.786,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -89.5,
        "boiling_point_c": 82.6,
        "ghs_pictograms": ["GHS02", "GHS07"],
        "h_phrases": ["H225", "H319", "H336"],
        "p_phrases": ["P210", "P233", "P280", "P305+P351+P338"],
        "pubchem_cid": 3776,
    },

    # ── Polar aprotic solvents ────────────────────────────────────
    {
        "name": "Dimetilsolfossido (DMSO)",
        "iupac_name": "dimethyl sulfoxide",
        "cas_number": "67-68-5",
        "molecular_formula": "C2H6OS",
        "molecular_weight": 78.13,
        "smiles": "CS(=O)C",
        "inchi": "InChI=1S/C2H6OS/c1-4(2)3/h1-2H3",
        "inchi_key": "IAZDPXIOMUYVGZ-UHFFFAOYSA-N",
        "density": 1.100,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": 19.0,
        "boiling_point_c": 189.0,
        "ghs_pictograms": [],
        "h_phrases": [],
        "p_phrases": [],
        "pubchem_cid": 679,
        "notes": "Non classificato come pericoloso secondo CLP, ma penetra "
                 "rapidamente la pelle: maneggiare con guanti idonei.",
    },
    {
        "name": "Dimetilformammide (DMF)",
        "iupac_name": "N,N-dimethylformamide",
        "cas_number": "68-12-2",
        "molecular_formula": "C3H7NO",
        "molecular_weight": 73.09,
        "smiles": "CN(C)C=O",
        "inchi": "InChI=1S/C3H7NO/c1-4(2)3-5/h3H,1-2H3",
        "inchi_key": "ZMXDDKWLCZADIW-UHFFFAOYSA-N",
        "density": 0.944,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -60.4,
        "boiling_point_c": 153.0,
        "ghs_pictograms": ["GHS02", "GHS07", "GHS08"],
        "h_phrases": ["H226", "H312", "H319", "H332", "H360D"],
        "p_phrases": ["P201", "P280", "P305+P351+P338", "P308+P313"],
        "pubchem_cid": 6228,
    },
    {
        "name": "Acetonitrile",
        "iupac_name": "acetonitrile",
        "cas_number": "75-05-8",
        "molecular_formula": "C2H3N",
        "molecular_weight": 41.05,
        "smiles": "CC#N",
        "inchi": "InChI=1S/C2H3N/c1-2-3/h1H3",
        "inchi_key": "WEVYAHXRMPXWCK-UHFFFAOYSA-N",
        "density": 0.786,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": -45.7,
        "boiling_point_c": 81.6,
        "ghs_pictograms": ["GHS02", "GHS07"],
        "h_phrases": ["H225", "H302", "H312", "H319", "H332"],
        "p_phrases": ["P210", "P280", "P305+P351+P338"],
        "pubchem_cid": 6342,
    },

    # ── Mineral acids ─────────────────────────────────────────────
    {
        "name": "Acido cloridrico (HCl, gas)",
        "iupac_name": "hydrogen chloride",
        "cas_number": "7647-01-0",
        "molecular_formula": "HCl",
        "molecular_weight": 36.46,
        "smiles": "Cl",
        "inchi": "InChI=1S/ClH/h1H",
        "inchi_key": "VEXZGXHMUGYJMC-UHFFFAOYSA-N",
        "density": None,
        "state": "gas",
        "is_solvent": False,
        "melting_point_c": -114.2,
        "boiling_point_c": -85.0,
        "ghs_pictograms": ["GHS05", "GHS06"],
        "h_phrases": ["H280", "H314", "H331"],
        "p_phrases": ["P260", "P280", "P303+P361+P353", "P305+P351+P338"],
        "pubchem_cid": 313,
        "notes": "Anidro. Usato in soluzione acquosa per preparare HCl 12N, 6N, ecc.",
    },
    {
        "name": "Acido solforico (98 %)",
        "iupac_name": "sulfuric acid",
        "cas_number": "7664-93-9",
        "molecular_formula": "H2SO4",
        "molecular_weight": 98.08,
        "smiles": "OS(=O)(=O)O",
        "inchi": "InChI=1S/H2O4S/c1-5(2,3)4/h(H2,1,2,3,4)",
        "inchi_key": "QAOWNCQODCNURD-UHFFFAOYSA-N",
        "density": 1.84,
        "state": "liquid",
        "is_solvent": False,
        "melting_point_c": 10.0,
        "boiling_point_c": 337.0,
        "ghs_pictograms": ["GHS05"],
        "h_phrases": ["H290", "H314"],
        "p_phrases": ["P260", "P280", "P303+P361+P353", "P305+P351+P338"],
        "pubchem_cid": 1118,
    },
    {
        "name": "Acido nitrico (65 %)",
        "iupac_name": "nitric acid",
        "cas_number": "7697-37-2",
        "molecular_formula": "HNO3",
        "molecular_weight": 63.01,
        "smiles": "O[N+](=O)[O-]",
        "inchi": "InChI=1S/HNO3/c2-1(3)4/h(H,2,3,4)",
        "inchi_key": "GRYLNZFGIOXLOG-UHFFFAOYSA-N",
        "density": 1.40,
        "state": "liquid",
        "is_solvent": False,
        "melting_point_c": -42.0,
        "boiling_point_c": 121.0,
        "ghs_pictograms": ["GHS03", "GHS05", "GHS06"],
        "h_phrases": ["H272", "H290", "H314", "H331"],
        "p_phrases": ["P210", "P220", "P280", "P303+P361+P353"],
        "pubchem_cid": 944,
    },
    {
        "name": "Acido acetico glaciale",
        "iupac_name": "acetic acid",
        "cas_number": "64-19-7",
        "molecular_formula": "C2H4O2",
        "molecular_weight": 60.05,
        "smiles": "CC(=O)O",
        "inchi": "InChI=1S/C2H4O2/c1-2(3)4/h1H3,(H,3,4)",
        "inchi_key": "QTBSBXVTEAMEQO-UHFFFAOYSA-N",
        "density": 1.049,
        "state": "liquid",
        "is_solvent": False,
        "melting_point_c": 16.6,
        "boiling_point_c": 118.0,
        "ghs_pictograms": ["GHS02", "GHS05"],
        "h_phrases": ["H226", "H290", "H314"],
        "p_phrases": ["P210", "P280", "P303+P361+P353", "P305+P351+P338"],
        "pubchem_cid": 176,
    },

    # ── Bases ─────────────────────────────────────────────────────
    {
        "name": "Idrossido di sodio (NaOH)",
        "iupac_name": "sodium hydroxide",
        "cas_number": "1310-73-2",
        "molecular_formula": "NaOH",
        "molecular_weight": 40.00,
        "smiles": "[Na+].[OH-]",
        "inchi": "InChI=1S/Na.H2O/h;1H2/q+1;/p-1",
        "inchi_key": "HEMHJVSKTPXQMS-UHFFFAOYSA-M",
        "density": 2.13,
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": 318.0,
        "boiling_point_c": 1388.0,
        "ghs_pictograms": ["GHS05"],
        "h_phrases": ["H290", "H314"],
        "p_phrases": ["P260", "P280", "P303+P361+P353", "P305+P351+P338"],
        "pubchem_cid": 14798,
    },
    {
        "name": "Idrossido di potassio (KOH)",
        "iupac_name": "potassium hydroxide",
        "cas_number": "1310-58-3",
        "molecular_formula": "KOH",
        "molecular_weight": 56.11,
        "smiles": "[K+].[OH-]",
        "inchi": "InChI=1S/K.H2O/h;1H2/q+1;/p-1",
        "inchi_key": "KWYUFKZDYYNOTN-UHFFFAOYSA-M",
        "density": 2.044,
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": 360.0,
        "boiling_point_c": 1327.0,
        "ghs_pictograms": ["GHS05", "GHS07"],
        "h_phrases": ["H290", "H302", "H314"],
        "p_phrases": ["P260", "P280", "P303+P361+P353", "P305+P351+P338"],
        "pubchem_cid": 14797,
    },
    {
        "name": "Ammoniaca (NH3, soluzione 25 %)",
        "iupac_name": "ammonia",
        "cas_number": "1336-21-6",
        "molecular_formula": "NH3·H2O",
        "molecular_weight": 17.03,
        "smiles": "N",
        "inchi": "InChI=1S/H3N/h1H3",
        "inchi_key": "QGZKDVFQNNGYKY-UHFFFAOYSA-N",
        "density": 0.91,
        "state": "liquid",
        "is_solvent": False,
        "melting_point_c": -77.7,
        "boiling_point_c": 38.0,
        "ghs_pictograms": ["GHS05", "GHS07", "GHS09"],
        "h_phrases": ["H290", "H314", "H335", "H400"],
        "p_phrases": ["P260", "P273", "P280", "P303+P361+P353"],
        "pubchem_cid": 222,
        "notes": "Soluzione acquosa concentrata (~25 % w/w).",
    },

    # ── Buffers / saline ──────────────────────────────────────────
    {
        "name": "Carbonato di sodio (Na2CO3)",
        "iupac_name": "sodium carbonate",
        "cas_number": "497-19-8",
        "molecular_formula": "Na2CO3",
        "molecular_weight": 105.99,
        "smiles": "[Na+].[Na+].[O-]C(=O)[O-]",
        "inchi": "InChI=1S/CH2O3.2Na/c2-1(3)4;;/h(H2,2,3,4);;/q;2*+1/p-2",
        "inchi_key": "CDBYLPFSWZWCQE-UHFFFAOYSA-L",
        "density": 2.54,
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": 851.0,
        "boiling_point_c": None,
        "ghs_pictograms": ["GHS07"],
        "h_phrases": ["H319"],
        "p_phrases": ["P280", "P305+P351+P338"],
        "pubchem_cid": 10340,
    },
    {
        "name": "Bicarbonato di sodio (NaHCO3)",
        "iupac_name": "sodium bicarbonate",
        "cas_number": "144-55-8",
        "molecular_formula": "NaHCO3",
        "molecular_weight": 84.01,
        "smiles": "[Na+].OC([O-])=O",
        "inchi": "InChI=1S/CH2O3.Na/c2-1(3)4;/h(H2,2,3,4);/q;+1/p-1",
        "inchi_key": "UIIMBOGNXHQVGW-UHFFFAOYSA-M",
        "density": 2.20,
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": 50.0,  # decompone
        "boiling_point_c": None,
        "ghs_pictograms": [],
        "h_phrases": [],
        "p_phrases": [],
        "pubchem_cid": 516892,
        "notes": "Non classificato come pericoloso. Decompone a circa 50 °C.",
    },
    {
        "name": "Cloruro di sodio (NaCl)",
        "iupac_name": "sodium chloride",
        "cas_number": "7647-14-5",
        "molecular_formula": "NaCl",
        "molecular_weight": 58.44,
        "smiles": "[Na+].[Cl-]",
        "inchi": "InChI=1S/ClH.Na/h1H;/q;+1/p-1",
        "inchi_key": "FAPWRFPIFSIZLT-UHFFFAOYSA-M",
        "density": 2.165,
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": 801.0,
        "boiling_point_c": 1413.0,
        "ghs_pictograms": [],
        "h_phrases": [],
        "p_phrases": [],
        "pubchem_cid": 5234,
    },

    # ── Drying agents ─────────────────────────────────────────────
    {
        "name": "Solfato di sodio anidro (Na2SO4)",
        "iupac_name": "sodium sulfate",
        "cas_number": "7757-82-6",
        "molecular_formula": "Na2SO4",
        "molecular_weight": 142.04,
        "smiles": "[Na+].[Na+].[O-]S(=O)(=O)[O-]",
        "inchi": "InChI=1S/2Na.H2O4S/c;;1-5(2,3)4/h;;(H2,1,2,3,4)/q2*+1;/p-2",
        "inchi_key": "PMZURENOXWZQFD-UHFFFAOYSA-L",
        "density": 2.66,
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": 884.0,
        "boiling_point_c": 1429.0,
        "ghs_pictograms": [],
        "h_phrases": [],
        "p_phrases": [],
        "pubchem_cid": 24436,
        "notes": "Agente disidratante per fase organica. Granulare, "
                 "capacità ~25 % w/w di acqua.",
    },
    {
        "name": "Solfato di magnesio anidro (MgSO4)",
        "iupac_name": "magnesium sulfate",
        "cas_number": "7487-88-9",
        "molecular_formula": "MgSO4",
        "molecular_weight": 120.37,
        "smiles": "[Mg+2].[O-]S(=O)(=O)[O-]",
        "inchi": "InChI=1S/Mg.H2O4S/c;1-5(2,3)4/h;(H2,1,2,3,4)/q+2;/p-2",
        "inchi_key": "CSNNHWWHGAXBCP-UHFFFAOYSA-L",
        "density": 2.66,
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": 1124.0,
        "boiling_point_c": None,
        "ghs_pictograms": [],
        "h_phrases": [],
        "p_phrases": [],
        "pubchem_cid": 24083,
        "notes": "Agente disidratante più aggressivo del Na2SO4 ma "
                 "leggermente acido in soluzione.",
    },

    # ── Reducing / other extras ───────────────────────────────────
    {
        "name": "Tiosolfato di sodio (Na2S2O3)",
        "iupac_name": "sodium thiosulfate",
        "cas_number": "7772-98-7",
        "molecular_formula": "Na2S2O3",
        "molecular_weight": 158.11,
        "smiles": "[Na+].[Na+].[O-]S(=O)(=O)[S-]",
        "inchi": "InChI=1S/2Na.H2O3S2/c;;1-5(2,3)4/h;;(H2,1,2,3,4)/q2*+1;/p-2",
        "inchi_key": "AKHNMLFCWUSKQB-UHFFFAOYSA-L",
        "density": 1.667,
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": 48.0,
        "boiling_point_c": None,
        "ghs_pictograms": [],
        "h_phrases": [],
        "p_phrases": [],
        "pubchem_cid": 24477,
        "notes": "Usato per quench di soluzioni iodate o di Br2.",
    },
    {
        "name": "Silice gel 60 (60–230 mesh)",
        "iupac_name": "silica gel",
        "cas_number": "112926-00-8",
        "molecular_formula": "SiO2",
        "molecular_weight": 60.08,
        "smiles": None,
        "inchi": None,
        "inchi_key": None,
        "density": 0.75,  # bulk
        "state": "solid",
        "is_solvent": False,
        "melting_point_c": None,
        "boiling_point_c": None,
        "ghs_pictograms": [],
        "h_phrases": [],
        "p_phrases": [],
        "pubchem_cid": None,
        "notes": "Silice per cromatografia flash, dimensione 60–230 mesh "
                 "(40–63 µm). Polvere irritante per le vie respiratorie: "
                 "usare con mascherina FFP2 o sotto cappa.",
    },
    {
        "name": "Acqua deionizzata",
        "iupac_name": "water",
        "cas_number": "7732-18-5",
        "molecular_formula": "H2O",
        "molecular_weight": 18.02,
        "smiles": "O",
        "inchi": "InChI=1S/H2O/h1H2",
        "inchi_key": "XLYOFNOQVPJJNP-UHFFFAOYSA-N",
        "density": 0.998,
        "state": "liquid",
        "is_solvent": True,
        "melting_point_c": 0.0,
        "boiling_point_c": 100.0,
        "ghs_pictograms": [],
        "h_phrases": [],
        "p_phrases": [],
        "pubchem_cid": 962,
        "notes": "Acqua deionizzata (resistività > 1 MΩ·cm). "
                 "Per applicazioni che richiedono Milli-Q creare un'entry separata.",
    },
]


# ─── Seeder ──────────────────────────────────────────────────────


def seed(*, dry_run: bool = False) -> tuple[int, int]:
    """Insert the substances. Returns (inserted, skipped) tuple.

    Idempotent: for each entry, looks up by CAS number first
    (the most stable identifier). If found, skipped. If not,
    inserted. Substances without CAS (rare — mixtures) fall back
    to name-based lookup.
    """
    inserted = 0
    skipped = 0
    for entry in COMMON_SUBSTANCES:
        cas = entry.get("cas_number")
        existing = None
        if cas:
            existing = db.session.query(Substance).filter_by(
                cas_number=cas,
            ).first()
        if existing is None:
            # Fallback by name (case-insensitive exact match)
            existing = db.session.query(Substance).filter(
                Substance.name.ilike(entry["name"])
            ).first()

        if existing is not None:
            print(f"  ⊘ skip:    {entry['name']}  (already present, id={existing.id})")
            skipped += 1
            continue

        if dry_run:
            print(f"  → would insert: {entry['name']}")
            inserted += 1
            continue

        sub = Substance(**entry)
        db.session.add(sub)
        print(f"  ✓ insert:  {entry['name']}")
        inserted += 1

    if not dry_run:
        db.session.commit()

    return inserted, skipped


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Seed Stoic with common substances.")
    p.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without writing to the DB.",
    )
    args = p.parse_args()

    app = create_app()
    with app.app_context():
        print(f"\nSeeding {len(COMMON_SUBSTANCES)} common substances "
              f"({'dry run' if args.dry_run else 'live'}):\n")
        inserted, skipped = seed(dry_run=args.dry_run)
        print()
        print(f"Result: {inserted} inserted, {skipped} skipped "
              f"(already present).")
        if args.dry_run:
            print("(dry run — no changes committed)")


if __name__ == "__main__":
    main()
