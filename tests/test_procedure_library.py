"""Tests for the procedure library (StepTemplate) — P1.

The two copy directions are the heart of the feature:

  reaction step → library   (save_from_step, with overwrite handling)
  library → reaction step   (insert_into_reaction)

Both must deep-copy components and checklist items so that library
and protocol never share rows — editing one must never mutate the
other (the copy-not-reference design in models/step_template.py).
"""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    ChecklistItem,
    Reaction,
    ReactionStep,
    ReactionStepComponent,
    StepTemplate,
    Substance,
    User,
)


@pytest.fixture()
def supervisor(app):
    with app.app_context():
        u = User(
            username="proc_sup",
            full_name="Proc Supervisor",
            operator_code="PS",
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


def _make_reaction_with_step(app) -> tuple[int, int]:
    """Reaction in draft with one step carrying a component and a
    checklist item. Returns (reaction_id, step_id)."""
    with app.app_context():
        sub = Substance(name="EtOAc-proc-test", molecular_weight=88.11)
        db.session.add(sub)
        db.session.flush()

        rxn = Reaction(code="RX-2026-0990", title="Proc test rxn", status="draft")
        db.session.add(rxn)
        db.session.flush()

        step = ReactionStep(
            reaction_id=rxn.id,
            position=0,
            kind="extraction",
            title="Workup acquoso standard",
            description="3 estrazioni, poi brine.",
        )
        db.session.add(step)
        db.session.flush()

        db.session.add(
            ReactionStepComponent(
                step_id=step.id,
                substance_id=sub.id,
                position=0,
                role="solvent",
                ratio_kind="mL_per_g",
                ratio_value=10.0,
            )
        )
        db.session.add(ChecklistItem(step_id=step.id, position=0, text="Controlla pH"))
        db.session.commit()
        return rxn.id, step.id


def test_save_step_to_library(app, logged_client):
    rxn_id, step_id = _make_reaction_with_step(app)

    r = logged_client.post(
        f"/procedures/save-from-step/{step_id}",
        data={"name": "Workup acquoso standard"},
        follow_redirects=False,
    )
    assert r.status_code == 302

    with app.app_context():
        tpl = StepTemplate.query.filter_by(name="Workup acquoso standard").one()
        assert tpl.kind == "extraction"
        assert len(tpl.components) == 1
        assert tpl.components[0].ratio_kind == "mL_per_g"
        assert tpl.components[0].ratio_value == 10.0
        assert len(tpl.checklist_items) == 1
        assert tpl.checklist_items[0].text == "Controlla pH"


def test_save_duplicate_name_requires_overwrite(app, logged_client):
    rxn_id, step_id = _make_reaction_with_step(app)

    logged_client.post(
        f"/procedures/save-from-step/{step_id}", data={"name": "Dup"}, follow_redirects=False
    )
    # Second save, same name, NO overwrite flag → must not create a
    # second template nor modify the first.
    logged_client.post(
        f"/procedures/save-from-step/{step_id}", data={"name": "Dup"}, follow_redirects=False
    )
    with app.app_context():
        assert StepTemplate.query.filter_by(name="Dup").count() == 1

    # With overwrite=1 → still one row, refreshed.
    logged_client.post(
        f"/procedures/save-from-step/{step_id}",
        data={"name": "Dup", "overwrite": "1"},
        follow_redirects=False,
    )
    with app.app_context():
        assert StepTemplate.query.filter_by(name="Dup").count() == 1


def test_insert_template_into_reaction_deep_copies(app, logged_client):
    rxn_id, step_id = _make_reaction_with_step(app)
    logged_client.post(
        f"/procedures/save-from-step/{step_id}",
        data={"name": "Insertable"},
        follow_redirects=False,
    )

    with app.app_context():
        tpl_id = StepTemplate.query.filter_by(name="Insertable").one().id
        steps_before = ReactionStep.query.filter_by(reaction_id=rxn_id).count()

    r = logged_client.post(f"/procedures/{tpl_id}/insert-into/{rxn_id}", follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        steps = (
            ReactionStep.query.filter_by(reaction_id=rxn_id).order_by(ReactionStep.position).all()
        )
        assert len(steps) == steps_before + 1
        new_step = steps[-1]
        assert new_step.title == "Insertable"
        assert new_step.kind == "extraction"
        assert len(new_step.components) == 1
        assert len(new_step.checklist_items) == 1

        # Deep copy: mutating the new step's component must not touch
        # the library row.
        new_step.components[0].ratio_value = 99.0
        db.session.commit()
        tpl = db.session.get(StepTemplate, tpl_id)
        assert tpl.components[0].ratio_value == 10.0


def test_rename_and_delete_template(app, logged_client):
    rxn_id, step_id = _make_reaction_with_step(app)
    logged_client.post(
        f"/procedures/save-from-step/{step_id}",
        data={"name": "ToRename"},
        follow_redirects=False,
    )
    with app.app_context():
        tpl_id = StepTemplate.query.filter_by(name="ToRename").one().id

    logged_client.post(f"/procedures/{tpl_id}/rename", data={"name": "Renamed"})
    with app.app_context():
        assert db.session.get(StepTemplate, tpl_id).name == "Renamed"

    logged_client.post(f"/procedures/{tpl_id}/delete")
    with app.app_context():
        assert db.session.get(StepTemplate, tpl_id) is None
        # Children gone too (cascade)
        from stoic_eln.models import StepTemplateComponent

        assert StepTemplateComponent.query.filter_by(template_id=tpl_id).count() == 0


def test_deleting_template_does_not_touch_protocol_steps(app, logged_client):
    """The promise in the UI confirm dialog: deleting a library entry
    leaves protocols that used it intact."""
    rxn_id, step_id = _make_reaction_with_step(app)
    logged_client.post(
        f"/procedures/save-from-step/{step_id}",
        data={"name": "Ephemeral"},
        follow_redirects=False,
    )
    with app.app_context():
        tpl_id = StepTemplate.query.filter_by(name="Ephemeral").one().id

    logged_client.post(f"/procedures/{tpl_id}/insert-into/{rxn_id}")
    with app.app_context():
        n_steps = ReactionStep.query.filter_by(reaction_id=rxn_id).count()

    logged_client.post(f"/procedures/{tpl_id}/delete")
    with app.app_context():
        assert ReactionStep.query.filter_by(reaction_id=rxn_id).count() == n_steps


def test_procedures_index_renders(app, logged_client):
    r = logged_client.get("/procedures/")
    assert r.status_code == 200
