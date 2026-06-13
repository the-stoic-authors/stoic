"""Tests for P2: free-entry step components + column diameter calc.

The column diameter is pure cylinder geometry from the silica load:
d_mm = 10 * 2 * sqrt((m/rho) / (pi*h)). The interesting contracts are
(a) the math, (b) the run-level resolution that finds the stationary
phase inside the same step, and (c) snapshot + library copies carrying
the free fields.
"""

from __future__ import annotations

import math

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    Reaction,
    ReactionStep,
    ReactionStepComponent,
    StepTemplate,
    Substance,
    User,
)
from stoic_eln.services.step_calc import (
    SILICA_BULK_DENSITY_G_PER_ML,
    compute_column_diameter_mm,
)


# ── The math ───────────────────────────────────────────────────────


def test_column_diameter_formula():
    """30 g silica → 60 mL bed; at 15 cm: d = 2·√(60/(15π)) cm."""
    d = compute_column_diameter_mm(30.0, 15.0)
    expected_cm = 2.0 * math.sqrt((30.0 / SILICA_BULK_DENSITY_G_PER_ML) / (math.pi * 15.0))
    assert d == pytest.approx(expected_cm * 10.0)
    assert d == pytest.approx(22.57, abs=0.05)


def test_column_diameter_scales_with_sqrt_of_mass():
    """4× the silica at fixed height → 2× the diameter."""
    d1 = compute_column_diameter_mm(30.0, 15.0)
    d4 = compute_column_diameter_mm(120.0, 15.0)
    assert d4 == pytest.approx(2.0 * d1)


def test_column_diameter_taller_bed_is_narrower():
    """Same silica, taller bed → narrower column (∝ 1/√h)."""
    d15 = compute_column_diameter_mm(50.0, 15.0)
    d20 = compute_column_diameter_mm(50.0, 20.0)
    assert d20 < d15
    assert d20 == pytest.approx(d15 * math.sqrt(15.0 / 20.0))


def test_column_diameter_degenerate_inputs():
    assert compute_column_diameter_mm(None, 15.0) is None
    assert compute_column_diameter_mm(30.0, None) is None
    assert compute_column_diameter_mm(0.0, 15.0) is None
    assert compute_column_diameter_mm(30.0, -5.0) is None


# ── Free entries through the web layer ─────────────────────────────


@pytest.fixture()
def supervisor(app):
    with app.app_context():
        u = User(
            username="p2_sup",
            full_name="P2 Supervisor",
            operator_code="P2",
            role="supervisor",
            is_admin=False,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
        return db.session.get(User, u.id)


@pytest.fixture()
def logged_client(app, client, supervisor):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(supervisor.id)
        sess["_fresh"] = True
    return client


def _make_draft_step(app) -> tuple[int, int]:
    with app.app_context():
        rxn = Reaction(code="RX-2026-0991", title="P2 rxn", status="draft")
        db.session.add(rxn)
        db.session.flush()
        step = ReactionStep(reaction_id=rxn.id, position=0, kind="purification", title="Flash")
        db.session.add(step)
        db.session.commit()
        return rxn.id, step.id


def test_add_free_entry_component(app, logged_client):
    rxn_id, step_id = _make_draft_step(app)
    r = logged_client.post(
        f"/reactions/steps/{step_id}/components/new",
        data={
            "free_name": "Colonna Ø",
            "free_unit": "mm",
            "role": "other",
            "ratio_kind": "column_diameter_mm",
            "ratio_value": "15",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    with app.app_context():
        sc = ReactionStepComponent.query.filter_by(step_id=step_id).one()
        assert sc.free_name == "Colonna Ø"
        assert sc.free_unit == "mm"
        assert sc.substance_id is None and sc.mixture_id is None
        assert sc.ratio_kind == "column_diameter_mm"
        assert sc.ratio_value == 15.0


def test_add_component_rejects_zero_or_two_choices(app, logged_client):
    rxn_id, step_id = _make_draft_step(app)
    # Nothing chosen
    logged_client.post(
        f"/reactions/steps/{step_id}/components/new",
        data={"role": "solvent", "ratio_kind": "eq"},
    )
    # Substance AND free entry
    with app.app_context():
        sub = Substance(name="P2-sub", molecular_weight=100.0)
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id
    logged_client.post(
        f"/reactions/steps/{step_id}/components/new",
        data={
            "substance_id": str(sub_id),
            "free_name": "Anche libera",
            "role": "solvent",
            "ratio_kind": "eq",
        },
    )
    with app.app_context():
        assert ReactionStepComponent.query.filter_by(step_id=step_id).count() == 0


def test_free_entry_survives_library_round_trip(app, logged_client):
    """Save a step with a free entry to the library, insert it into
    the reaction again: the free fields must survive both copies."""
    rxn_id, step_id = _make_draft_step(app)
    logged_client.post(
        f"/reactions/steps/{step_id}/components/new",
        data={
            "free_name": "Celite",
            "free_unit": "g",
            "role": "other",
            "ratio_kind": "fixed_value",
            "ratio_value": "5",
        },
    )
    logged_client.post(
        f"/procedures/save-from-step/{step_id}",
        data={"name": "Filtrazione celite"},
    )
    with app.app_context():
        tpl = StepTemplate.query.filter_by(name="Filtrazione celite").one()
        assert tpl.components[0].free_name == "Celite"
        assert tpl.components[0].free_unit == "g"
        tpl_id = tpl.id

    logged_client.post(f"/procedures/{tpl_id}/insert-into/{rxn_id}")
    with app.app_context():
        steps = (
            ReactionStep.query.filter_by(reaction_id=rxn_id).order_by(ReactionStep.position).all()
        )
        new_sc = steps[-1].components[0]
        assert new_sc.free_name == "Celite"
        assert new_sc.free_unit == "g"
        assert new_sc.ratio_kind == "fixed_value"
        assert new_sc.ratio_value == 5.0
