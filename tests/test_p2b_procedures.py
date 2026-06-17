"""Tests for P2b — standard procedure seeds + g_per_g + run-step reference.

Covers the three moving parts introduced together:

  1. ``g_per_g`` ratio kind (mass:mass loading, g-only).
  2. The run-step honouring its snapshotted reference component, so a
     flash silica load expressed "g per g of crude" computes against
     the PRODUCT mass, not the limiting reagent.
  3. ``seed_procedures`` building the 4 starter library entries,
     idempotently.
"""

from __future__ import annotations

import math

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    Reaction,
    ReactionComponent,
    ReactionStep,
    ReactionStepComponent,
    StepTemplate,
    Substance,
    User,
)
from stoic_eln.services import run_setup
from stoic_eln.services.step_calc import (
    StepQuantity,
    compute_column_diameter_mm,
    compute_run_step_component,
    compute_step_component,
)


# ── g_per_g unit behaviour ───────────────────────────────────────────


def test_g_per_g_is_mass_only():
    """g_per_g yields grams = ratio × reference grams, and ONLY grams
    (no skeletal mL / meaningless mmol)."""
    ref = StepQuantity(g=2.0, mL=1.0, mmol=20.0)
    out = compute_step_component(
        ratio_kind="g_per_g",
        ratio_value=30.0,
        ref_quantity=ref,
        sub_mw=60.08,
        sub_density=2.20,
    )
    assert out.g == pytest.approx(60.0)
    assert out.mL is None
    assert out.mmol is None


def test_g_per_g_needs_reference_grams():
    out = compute_step_component(
        ratio_kind="g_per_g",
        ratio_value=30.0,
        ref_quantity=StepQuantity(g=None),
        sub_mw=None,
        sub_density=None,
    )
    assert out.g is None


def test_column_diameter_geometry():
    # 30 g silica, bulk 0.5 g/mL → 60 mL bed; h=15 cm →
    # d = 2*sqrt(60/(pi*15)) cm = 22.57 mm
    d = compute_column_diameter_mm(30.0, 15.0)
    expected = 2.0 * math.sqrt((30.0 / 0.5) / (math.pi * 15.0)) * 10.0
    assert d == pytest.approx(expected)
    assert d == pytest.approx(22.57, abs=0.05)


# ── reference-at-run (B) end-to-end ──────────────────────────────────


def _flash_reaction(reference_on_product: bool):
    """Reaction: SM (limiting, MW 100) + product (MW 200), with a
    purification step carrying silica (g_per_g 30) + a Column Ø.
    If reference_on_product, the step references the product component.
    Returns reaction id.
    """
    sm = Substance(name="SM-p2b", molecular_weight=100.0)
    prod = Substance(name="PROD-p2b", molecular_weight=200.0)
    silica = Substance(name="Silica-p2b", molecular_weight=60.08, density=2.20)
    db.session.add_all([sm, prod, silica])
    db.session.flush()

    rxn = Reaction(code="RX-P2B-1", status="published", title="P2b flash")
    db.session.add(rxn)
    db.session.flush()

    c_sm = ReactionComponent(
        reaction_id=rxn.id,
        substance_id=sm.id,
        role="starting_material",
        position=0,
        is_limiting=True,
        equivalents=1.0,
    )
    c_prod = ReactionComponent(
        reaction_id=rxn.id,
        substance_id=prod.id,
        role="product",
        position=1,
        equivalents=1.0,
    )
    db.session.add_all([c_sm, c_prod])
    db.session.flush()

    step = ReactionStep(
        reaction_id=rxn.id,
        kind="purification",
        title="Flash",
        position=0,
        reference_component_id=(c_prod.id if reference_on_product else None),
    )
    db.session.add(step)
    db.session.flush()

    db.session.add_all(
        [
            ReactionStepComponent(
                step_id=step.id,
                substance_id=silica.id,
                role="stationary_phase",
                ratio_kind="g_per_g",
                ratio_value=30.0,
                position=0,
            ),
            ReactionStepComponent(
                step_id=step.id,
                free_name="Column Ø",
                free_unit="mm",
                role="additive",
                ratio_kind="column_diameter_mm",
                ratio_value=15.0,
                position=1,
            ),
        ]
    )
    db.session.commit()
    return rxn.id


@pytest.fixture()
def operator_user(app):
    with app.app_context():
        u = User(
            username="p2b_op",
            full_name="P2b Op",
            operator_code="PB",
            role="operator",
            is_admin=False,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
        return u.id


def test_run_step_snapshots_reference(app, operator_user):
    with app.app_context():
        rid = _flash_reaction(reference_on_product=True)
        rxn = db.session.get(Reaction, rid)
        op = db.session.get(User, operator_user)
        run = run_setup.create_draft(rxn, op)
        db.session.commit()

        rs = run.steps[0]
        assert rs.reference_run_component is not None
        # It maps to the PRODUCT run component, not the limiting one.
        assert rs.reference_run_component.role == "product"
        assert rs.reference_run_component.is_limiting is False


def test_silica_scales_with_product_when_referenced(app, operator_user):
    with app.app_context():
        rid = _flash_reaction(reference_on_product=True)
        rxn = db.session.get(Reaction, rid)
        op = db.session.get(User, operator_user)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        db.session.commit()

        rs = run.steps[0]
        silica = next(c for c in rs.components if c.role == "stationary_phase")
        col = next(c for c in rs.components if c.free_name == "Column Ø")

        # product mass = 5 mmol × 200 g/mol / 1000 = 1.0 g
        # silica = 30 g/g × 1.0 g = 30 g
        sq = compute_run_step_component(silica, run)
        assert sq.g == pytest.approx(30.0)

        # column Ø from 30 g silica, 15 cm bed
        cq = compute_run_step_component(col, run)
        assert cq.free == pytest.approx(compute_column_diameter_mm(30.0, 15.0))
        assert cq.free == pytest.approx(22.57, abs=0.05)


def test_silica_falls_back_to_limiting_without_reference(app, operator_user):
    with app.app_context():
        rid = _flash_reaction(reference_on_product=False)
        rxn = db.session.get(Reaction, rid)
        op = db.session.get(User, operator_user)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        db.session.commit()

        rs = run.steps[0]
        assert rs.reference_run_component is None
        silica = next(c for c in rs.components if c.role == "stationary_phase")

        # limiting (SM) mass = 5 × 100 / 1000 = 0.5 g → silica = 15 g
        sq = compute_run_step_component(silica, run)
        assert sq.g == pytest.approx(15.0)


# ── seed_procedures ──────────────────────────────────────────────────


def test_seed_procedures_creates_library(app):
    from stoic_eln.seeds.loader import seed_procedures, seed_substances
    from stoic_eln.seeds.procedures import PROCEDURES

    with app.app_context():
        seed_substances()  # silica + Na2SO4 must exist first
        added, skipped = seed_procedures()
        assert added == len(PROCEDURES)
        assert skipped == 0

        names = {t.name for t in db.session.query(StepTemplate).all()}
        assert "Flash chromatography — easy (ΔRf ≥ 0.3)" in names
        assert "Flash chromatography — medium (ΔRf 0.15–0.3)" in names
        assert "Flash chromatography — hard (ΔRf < 0.15)" in names
        assert "Standard extraction" in names

        easy = (
            db.session.query(StepTemplate)
            .filter_by(name="Flash chromatography — easy (ΔRf ≥ 0.3)")
            .first()
        )
        assert easy.kind == "purification"

        silica = next(c for c in easy.components if c.role == "stationary_phase")
        assert silica.ratio_kind == "g_per_g"
        assert silica.ratio_value == pytest.approx(30.0)
        assert silica.substance is not None  # resolved by InChIKey

        col = next(c for c in easy.components if c.free_name == "Column Ø")
        assert col.ratio_kind == "column_diameter_mm"
        assert col.ratio_value == pytest.approx(15.0)
        assert col.role != "stationary_phase"  # must not shadow the silica lookup

        eluent = next(c for c in easy.components if c.free_name == "Eluent")
        assert eluent.ratio_kind == "free"

        # Extraction: Na2SO4 is substance-backed (inventory-tracked), free q.b.
        extr = db.session.query(StepTemplate).filter_by(name="Standard extraction").first()
        assert extr.kind == "extraction"
        na2so4 = [c for c in extr.components if c.substance is not None]
        assert len(na2so4) == 1
        assert na2so4[0].ratio_kind == "free"


def test_seed_procedures_idempotent(app):
    from stoic_eln.seeds.loader import seed_procedures, seed_substances
    from stoic_eln.seeds.procedures import PROCEDURES

    with app.app_context():
        seed_substances()
        a1, s1 = seed_procedures()
        a2, s2 = seed_procedures()
        n = len(PROCEDURES)
        assert a1 == n and s1 == 0
        assert a2 == 0 and s2 == n  # all skipped second time


def test_procedure_library_page_renders_free_entries(app, client, operator_user):
    """The library page must render free-entry components without
    crashing (pre-P2b it did `c.mixture.name` on a None mixture)."""
    from stoic_eln.seeds.loader import seed_procedures, seed_substances

    with app.app_context():
        seed_substances()
        seed_procedures()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(operator_user)
        sess["_fresh"] = True

    resp = client.get("/procedures/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Column Ø" in body  # free entry rendered, no crash
    assert "Eluent" in body
    assert "Standard extraction" in body
