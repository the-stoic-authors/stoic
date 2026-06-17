"""Tests for P3 — recorded step parameters (distillation pressure / T, etc.).

The parameter infrastructure mirrors the checklist one across three
levels (StepTemplateParameter → StepParameter → RunStepParameter). These
tests cover the seeds, the two snapshot hops (template→reaction step→run),
the run-fill route, and that the run PDF renders recorded values.
"""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    Reaction,
    ReactionComponent,
    ReactionStep,
    StepParameter,
    Substance,
    User,
)
from stoic_eln.models.run import STATUS_COMPLETED
from stoic_eln.models.run_step import RunStepParameter
from stoic_eln.models.step_template import StepTemplate
from stoic_eln.services import run_setup
from stoic_eln.services.pdf_run import render_run_full


@pytest.fixture()
def operator_user(app):
    with app.app_context():
        u = User(
            username="p3_op",
            full_name="P3 Op",
            operator_code="P3",
            role="operator",
            is_admin=True,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
        return u.id


# ── seeds ────────────────────────────────────────────────────────────


def test_distillation_seeds_carry_parameters(app):
    from stoic_eln.seeds.loader import seed_procedures, seed_substances

    with app.app_context():
        seed_substances()
        seed_procedures()

        vac = db.session.query(StepTemplate).filter_by(name="Vacuum distillation").first()
        assert vac is not None
        labels = {(p.label, p.unit) for p in vac.parameters}
        assert ("Pressure", "mbar") in labels
        assert ("Head T start", "°C") in labels
        assert ("Head T end", "°C") in labels
        assert ("Bath T", "°C") in labels

        simple = db.session.query(StepTemplate).filter_by(name="Simple distillation").first()
        assert {p.label for p in simple.parameters} == {"Head T start", "Head T end"}


# ── copy chain: reaction step → run ──────────────────────────────────


def _reaction_with_param_step():
    sm = Substance(name="SM-p3", molecular_weight=120.0)
    db.session.add(sm)
    db.session.flush()
    rxn = Reaction(code="RX-P3-1", status="published", title="P3 distill")
    db.session.add(rxn)
    db.session.flush()
    db.session.add(
        ReactionComponent(
            reaction_id=rxn.id,
            substance_id=sm.id,
            role="starting_material",
            position=0,
            is_limiting=True,
            equivalents=1.0,
        )
    )
    step = ReactionStep(
        reaction_id=rxn.id,
        kind="purification",
        title="Vacuum distillation",
        position=0,
    )
    db.session.add(step)
    db.session.flush()
    db.session.add_all(
        [
            StepParameter(step_id=step.id, label="Pressure", unit="mbar", position=0),
            StepParameter(step_id=step.id, label="Head T start", unit="°C", position=1),
        ]
    )
    db.session.commit()
    return rxn.id


def test_parameters_copied_to_run(app, operator_user):
    with app.app_context():
        rid = _reaction_with_param_step()
        rxn = db.session.get(Reaction, rid)
        op = db.session.get(User, operator_user)
        run = run_setup.create_draft(rxn, op)
        db.session.commit()

        rs = run.steps[0]
        params = sorted(rs.parameters, key=lambda p: p.position)
        assert [(p.label, p.unit, p.value) for p in params] == [
            ("Pressure", "mbar", None),
            ("Head T start", "°C", None),
        ]


# ── copy chain: template → reaction step (insert route) ──────────────


def test_template_parameters_inserted_into_reaction(app, client, operator_user):
    from stoic_eln.seeds.loader import seed_procedures, seed_substances

    with app.app_context():
        seed_substances()
        seed_procedures()
        vac = db.session.query(StepTemplate).filter_by(name="Vacuum distillation").first()
        vac_id = vac.id

        rxn = Reaction(code="RX-P3-2", status="draft", title="host")
        db.session.add(rxn)
        db.session.commit()
        rid = rxn.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(operator_user)
        sess["_fresh"] = True

    resp = client.post(f"/procedures/{vac_id}/insert-into/{rid}")
    assert resp.status_code in (200, 302)

    with app.app_context():
        rxn = db.session.get(Reaction, rid)
        assert len(rxn.steps) == 1
        step = rxn.steps[0]
        labels = {p.label for p in step.parameters}
        assert {"Pressure", "Head T start", "Head T end", "Bath T"} <= labels


# ── run-fill route ───────────────────────────────────────────────────


def test_set_step_parameter_records_and_blocks_when_completed(app, client, operator_user):
    with app.app_context():
        rid = _reaction_with_param_step()
        rxn = db.session.get(Reaction, rid)
        op = db.session.get(User, operator_user)
        run = run_setup.create_draft(rxn, op)
        db.session.commit()
        run_id = run.id
        pid = run.steps[0].parameters[0].id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(operator_user)
        sess["_fresh"] = True

    resp = client.post(
        f"/runs/{run_id}/step-parameter/{pid}",
        data={"value": "12"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 204
    with app.app_context():
        assert db.session.get(RunStepParameter, pid).value == "12"

    # once completed, edits are blocked and the value is unchanged
    with app.app_context():
        from stoic_eln.models.run import Run

        run = db.session.get(Run, run_id)
        run.status = STATUS_COMPLETED
        db.session.commit()

    client.post(
        f"/runs/{run_id}/step-parameter/{pid}",
        data={"value": "999"},
        headers={"HX-Request": "true"},
    )
    with app.app_context():
        assert db.session.get(RunStepParameter, pid).value == "12"


# ── PDF ──────────────────────────────────────────────────────────────


def test_run_pdf_renders_with_recorded_parameters(app, operator_user):
    with app.app_context():
        rid = _reaction_with_param_step()
        rxn = db.session.get(Reaction, rid)
        op = db.session.get(User, operator_user)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        prm = run.steps[0].parameters[0]
        prm.value = "12"  # recorded pressure
        db.session.commit()

        pdf = render_run_full(run)
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1500  # the param-rendering branch executed without error
