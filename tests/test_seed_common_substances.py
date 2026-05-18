"""Tests for the common-substances seed script."""

from __future__ import annotations

import sys
from pathlib import Path

# Make sibling 'scripts' directory importable for these tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stoic_eln.extensions import db
from stoic_eln.models import Substance


def test_seed_inserts_substances_on_empty_db(app):
    """Fresh DB → all 30 substances inserted, none skipped."""
    from scripts.seed_common_substances import seed, COMMON_SUBSTANCES

    with app.app_context():
        # Ensure clean state: no substances with these CAS numbers
        cas_numbers = [e["cas_number"] for e in COMMON_SUBSTANCES if e.get("cas_number")]
        for cas in cas_numbers:
            existing = db.session.query(Substance).filter_by(cas_number=cas).first()
            if existing:
                db.session.delete(existing)
        db.session.commit()

        inserted, skipped = seed()
        assert inserted == len(COMMON_SUBSTANCES)
        assert skipped == 0


def test_seed_is_idempotent(app):
    """Running twice → second run inserts nothing, skips everything."""
    from scripts.seed_common_substances import seed, COMMON_SUBSTANCES

    with app.app_context():
        # Clean state
        for entry in COMMON_SUBSTANCES:
            cas = entry.get("cas_number")
            if cas:
                existing = db.session.query(Substance).filter_by(cas_number=cas).first()
                if existing:
                    db.session.delete(existing)
        db.session.commit()

        # First run
        seed()
        # Second run
        inserted, skipped = seed()
        assert inserted == 0
        assert skipped == len(COMMON_SUBSTANCES)


def test_seed_dry_run_changes_nothing(app):
    """dry_run=True must not touch the DB."""
    from scripts.seed_common_substances import seed

    with app.app_context():
        # Clean: delete water (CAS 7732-18-5) if present, so we
        # have a known "would insert" case.
        water = db.session.query(Substance).filter_by(
            cas_number="7732-18-5"
        ).first()
        if water:
            db.session.delete(water)
        db.session.commit()

        # Dry run
        seed(dry_run=True)

        # Water should still NOT be there
        water_after = db.session.query(Substance).filter_by(
            cas_number="7732-18-5"
        ).first()
        assert water_after is None


def test_seeded_substances_have_required_fields(app):
    """Sanity-check that the seed data is well-formed: every entry
    has name + (cas OR smiles), and the SMILES (when present)
    parses with RDKit."""
    from scripts.seed_common_substances import COMMON_SUBSTANCES

    for entry in COMMON_SUBSTANCES:
        assert entry.get("name"), f"Missing name: {entry}"
        # CAS or SMILES must be present (one identifier minimum)
        assert entry.get("cas_number") or entry.get("smiles"), \
            f"No CAS or SMILES: {entry['name']}"
        # state must be valid
        assert entry.get("state") in (None, "solid", "liquid", "gas"), \
            f"Bad state on {entry['name']}: {entry.get('state')}"


def test_seeded_smiles_parse_with_rdkit(app):
    """Every SMILES in the seed must be parseable by RDKit so
    the import preview and depiction work."""
    try:
        from rdkit import Chem
    except ImportError:
        import pytest
        pytest.skip("RDKit not available")

    from scripts.seed_common_substances import COMMON_SUBSTANCES

    failures = []
    for entry in COMMON_SUBSTANCES:
        smi = entry.get("smiles")
        if not smi:
            continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            failures.append(f"{entry['name']}: {smi!r}")
    assert not failures, f"Unparseable SMILES: {failures}"


def test_water_seed_entry(app):
    """Concrete spot-check: water is correctly seeded with the
    canonical values."""
    from scripts.seed_common_substances import seed

    with app.app_context():
        # Clean state
        water = db.session.query(Substance).filter_by(
            cas_number="7732-18-5"
        ).first()
        if water:
            db.session.delete(water)
        db.session.commit()

        seed()

        water = db.session.query(Substance).filter_by(
            cas_number="7732-18-5"
        ).one()
        assert water.name == "Acqua deionizzata"
        assert water.molecular_formula == "H2O"
        assert water.state == "liquid"
        assert water.is_solvent is True
        assert water.smiles == "O"


def test_naoh_seed_entry_has_hazards(app):
    """NaOH should have GHS05 (corrosive) and H290 / H314."""
    from scripts.seed_common_substances import seed

    with app.app_context():
        naoh = db.session.query(Substance).filter_by(
            cas_number="1310-73-2"
        ).first()
        if naoh:
            db.session.delete(naoh)
        db.session.commit()

        seed()

        naoh = db.session.query(Substance).filter_by(
            cas_number="1310-73-2"
        ).one()
        assert "GHS05" in naoh.ghs_pictograms
        assert "H314" in naoh.h_phrases
        assert "H290" in naoh.h_phrases
