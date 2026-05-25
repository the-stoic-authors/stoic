"""Tests for reaction checklists, steps, and step components."""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.checklist_item import ChecklistItem
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_component import ReactionComponent
from stoic_eln.models.reaction_step import ReactionStep
from stoic_eln.models.reaction_step_component import ReactionStepComponent
from stoic_eln.models.substance import Substance
from stoic_eln.services import step_calc


# ─── step_calc service ──────────────────────────────────────────────────────


def test_step_calc_eq():
    """3 eq of NaCl relative to a reference at 1 mmol → 3 mmol."""
    ref = step_calc.reference_quantities(
        ref_equivalents=1.0, scale_mmol=1.0,
        ref_mw=100.0, ref_density=None,
    )
    qty = step_calc.compute_step_component(
        ratio_kind="eq", ratio_value=3.0, ref_quantity=ref,
        sub_mw=58.44, sub_density=None,
    )
    assert qty.mmol == pytest.approx(3.0)
    assert qty.g == pytest.approx(3.0 * 58.44 / 1000.0)


def test_step_calc_mL_per_g():
    """10 mL water per gram of crude (1 g) → 10 mL."""
    ref = step_calc.reference_quantities(
        ref_equivalents=1.0, scale_mmol=10.0,
        ref_mw=100.0, ref_density=None,
    )
    # 10 mmol × 100 g/mol / 1000 = 1 g
    assert ref.g == pytest.approx(1.0)

    qty = step_calc.compute_step_component(
        ratio_kind="mL_per_g", ratio_value=10.0, ref_quantity=ref,
        sub_mw=18.0, sub_density=1.0,
    )
    assert qty.mL == pytest.approx(10.0)
    assert qty.g == pytest.approx(10.0)
    assert qty.mmol == pytest.approx(10.0 * 1000 / 18.0, abs=0.01)


def test_step_calc_mL_per_mmol():
    """20 mL EtOAc per mmol limiting (5 mmol) → 100 mL."""
    ref = step_calc.reference_quantities(
        ref_equivalents=1.0, scale_mmol=5.0,
        ref_mw=200.0, ref_density=None,
    )
    qty = step_calc.compute_step_component(
        ratio_kind="mL_per_mmol", ratio_value=20.0, ref_quantity=ref,
        sub_mw=88.11, sub_density=0.902,
    )
    assert qty.mL == pytest.approx(100.0)


def test_step_calc_percent_vv():
    """5% v/v of TFA in 100 mL of reference solvent → 5 mL TFA."""
    ref = step_calc.reference_quantities(
        ref_equivalents=1.0, scale_mmol=10.0,
        ref_mw=18.0, ref_density=1.0,  # 10 mmol × 18 / 1000 = 0.18 g; 0.18 / 1 = 0.18 mL
    )
    # The reference at scale 10 mmol with MW=18, ρ=1 → 0.18 g, 0.18 mL
    assert ref.mL == pytest.approx(0.18, abs=0.01)
    qty = step_calc.compute_step_component(
        ratio_kind="percent_vv", ratio_value=5.0, ref_quantity=ref,
        sub_mw=114.02, sub_density=1.489,
    )
    assert qty.mL == pytest.approx(0.18 * 5 / 100, abs=0.001)


def test_step_calc_absolute_mL():
    """Absolute volume — independent of reference."""
    ref = step_calc.reference_quantities(
        ref_equivalents=1.0, scale_mmol=999,
        ref_mw=100.0, ref_density=1.0,
    )
    qty = step_calc.compute_step_component(
        ratio_kind="absolute_mL", ratio_value=30.0, ref_quantity=ref,
        sub_mw=58.44, sub_density=1.0,
    )
    assert qty.mL == pytest.approx(30.0)
    assert qty.g == pytest.approx(30.0)


def test_step_calc_absolute_g():
    """Absolute mass — independent of reference."""
    ref = step_calc.reference_quantities(
        ref_equivalents=1.0, scale_mmol=1.0,
        ref_mw=100.0, ref_density=None,
    )
    qty = step_calc.compute_step_component(
        ratio_kind="absolute_g", ratio_value=2.5, ref_quantity=ref,
        sub_mw=142.04, sub_density=None,
    )
    assert qty.g == pytest.approx(2.5)
    assert qty.mmol == pytest.approx(2.5 * 1000 / 142.04, abs=0.01)


def test_step_calc_no_reference_returns_empty():
    """Without a usable reference, step component returns empty quantity."""
    ref = step_calc.StepQuantity()  # all None
    qty = step_calc.compute_step_component(
        ratio_kind="eq", ratio_value=3.0, ref_quantity=ref,
        sub_mw=100.0, sub_density=None,
    )
    assert qty.mmol is None and qty.g is None and qty.mL is None


# ─── Models: ChecklistItem ──────────────────────────────────────────────────


def test_checklist_item_on_reaction(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn)
        db.session.flush()
        item = ChecklistItem(reaction_id=rxn.id, position=0, text="Anidrificare il pallone")
        db.session.add(item)
        db.session.commit()
        assert item.id is not None
        assert item.reaction_id == rxn.id
        assert item.step_id is None
        assert rxn.checklist_items[0].text == "Anidrificare il pallone"


def test_checklist_constraint_xor(app):
    """Cannot have BOTH reaction_id and step_id set."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn)
        db.session.flush()
        step = ReactionStep(
            reaction_id=rxn.id, position=0, kind="workup", title="Workup"
        )
        db.session.add(step)
        db.session.flush()

        item = ChecklistItem(
            reaction_id=rxn.id, step_id=step.id, position=0, text="Bad"
        )
        db.session.add(item)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


def test_reaction_step_create(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn)
        db.session.flush()
        step = ReactionStep(
            reaction_id=rxn.id, position=0, kind="workup",
            title="Workup acquoso",
            description="Spegnere con NH4Cl, estrarre EtOAc x 3",
        )
        db.session.add(step)
        db.session.commit()
        assert step.id is not None
        assert step.kind == "workup"
        assert rxn.steps[0].title == "Workup acquoso"


def test_reaction_step_with_checklist(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn)
        db.session.flush()
        step = ReactionStep(
            reaction_id=rxn.id, position=0, kind="extraction", title="Estrazione"
        )
        db.session.add(step)
        db.session.flush()
        db.session.add_all([
            ChecklistItem(step_id=step.id, position=0, text="Separare le fasi"),
            ChecklistItem(step_id=step.id, position=1, text="Lavare con brine"),
        ])
        db.session.commit()
        assert len(step.checklist_items) == 2
        assert step.checklist_items[0].text == "Separare le fasi"


def test_reaction_step_components_with_ratios(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test", default_scale_mmol=10.0)
        sm = Substance(name="SM", molecular_weight=200.0)
        water = Substance(name="Water", molecular_weight=18.0, density=1.0)
        etoac = Substance(name="EtOAc", molecular_weight=88.11, density=0.902)
        db.session.add_all([rxn, sm, water, etoac])
        db.session.flush()

        sm_comp = ReactionComponent(
            reaction_id=rxn.id, substance_id=sm.id, role="starting_material",
            position=0, equivalents=1.0, is_limiting=True,
        )
        db.session.add(sm_comp)
        db.session.flush()

        step = ReactionStep(
            reaction_id=rxn.id, position=0, kind="workup", title="Workup",
        )
        db.session.add(step)
        db.session.flush()

        # 10 mL of water per gram of SM (which is 10 mmol × 200 / 1000 = 2 g) → 20 mL
        sc1 = ReactionStepComponent(
            step_id=step.id, substance_id=water.id, position=0,
            role="solvent", ratio_kind="mL_per_g", ratio_value=10.0,
        )
        # 20 mL of EtOAc per mmol of SM (10 mmol) → 200 mL
        sc2 = ReactionStepComponent(
            step_id=step.id, substance_id=etoac.id, position=1,
            role="solvent", ratio_kind="mL_per_mmol", ratio_value=20.0,
        )
        db.session.add_all([sc1, sc2])
        db.session.commit()

        assert len(step.components) == 2
        assert step.components[0].ratio_kind == "mL_per_g"
        assert step.components[1].ratio_kind == "mL_per_mmol"


def test_reaction_default_scale_mmol(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn)
        db.session.commit()
        # Default value
        assert rxn.default_scale_mmol == 1.0


# ─── Routes ─────────────────────────────────────────────────────────────────


def _login(client, app):
    from stoic_eln.models.user import User

    with app.app_context():
        if db.session.query(User).filter_by(username="admin").first() is None:
            u = User(username="admin", full_name="Admin", operator_code="ADM",
                     is_admin=True, is_active=True, locale="it")
            u.set_password("password123")
            db.session.add(u); db.session.commit()
    client.post("/auth/login", data={
        "username": "admin", "password": "password123", "submit": "Accedi"
    })


def test_add_checklist_item_route(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn); db.session.commit()
        rid = rxn.id

    _login(client, app)
    resp = client.post(
        f"/reactions/{rid}/checklist/new",
        data={"text": "Pesare il reagente"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        items = db.session.query(ChecklistItem).filter_by(reaction_id=rid).all()
        assert len(items) == 1
        assert items[0].text == "Pesare il reagente"
        assert items[0].is_default_done is False


def test_toggle_checklist_item(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn); db.session.flush()
        item = ChecklistItem(reaction_id=rxn.id, position=0, text="Foo")
        db.session.add(item); db.session.commit()
        iid = item.id

    _login(client, app)
    resp = client.post(f"/reactions/checklist/{iid}/toggle", follow_redirects=False)
    assert resp.status_code in (200, 302)
    with app.app_context():
        item = db.session.get(ChecklistItem, iid)
        assert item.is_default_done is True

    # Toggle again
    client.post(f"/reactions/checklist/{iid}/toggle")
    with app.app_context():
        item = db.session.get(ChecklistItem, iid)
        assert item.is_default_done is False


def test_delete_checklist_item(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn); db.session.flush()
        item = ChecklistItem(reaction_id=rxn.id, position=0, text="Foo")
        db.session.add(item); db.session.commit()
        iid = item.id

    _login(client, app)
    resp = client.post(f"/reactions/checklist/{iid}/delete", follow_redirects=False)
    assert resp.status_code in (200, 302)
    with app.app_context():
        assert db.session.get(ChecklistItem, iid) is None


def test_add_step_route(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn); db.session.commit()
        rid = rxn.id

    _login(client, app)
    resp = client.post(
        f"/reactions/{rid}/steps/new",
        data={"title": "Workup acquoso", "kind": "workup",
              "description": "Spegnere con NH4Cl"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        steps = db.session.query(ReactionStep).filter_by(reaction_id=rid).all()
        assert len(steps) == 1
        assert steps[0].kind == "workup"
        assert steps[0].title == "Workup acquoso"
        # Redirect should include the new step's anchor, so the
        # browser scrolls to it rather than jumping to the top.
        assert f"#step-card-{steps[0].id}" in resp.headers["Location"]


def test_add_step_component(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sub = Substance(name="Water", molecular_weight=18.0, density=1.0)
        db.session.add_all([rxn, sub]); db.session.flush()
        step = ReactionStep(
            reaction_id=rxn.id, position=0, kind="workup", title="WUP"
        )
        db.session.add(step); db.session.commit()
        sid = step.id; sub_id = sub.id

    _login(client, app)
    resp = client.post(
        f"/reactions/steps/{sid}/components/new",
        data={
            "substance_id": str(sub_id),
            "role": "solvent",
            "ratio_kind": "mL_per_g",
            "ratio_value": "10.0",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        sc = db.session.query(ReactionStepComponent).filter_by(step_id=sid).first()
        assert sc is not None
        assert sc.ratio_kind == "mL_per_g"
        assert sc.ratio_value == 10.0


def test_update_scale(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn); db.session.commit()
        rid = rxn.id

    _login(client, app)
    client.post(
        f"/reactions/{rid}/scale",
        data={"scale": "5.0"},
    )
    with app.app_context():
        rxn = db.session.get(Reaction, rid)
        assert rxn.default_scale_mmol == 5.0


def test_invalid_scale_falls_back_to_one(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        db.session.add(rxn); db.session.commit()
        rid = rxn.id

    _login(client, app)
    client.post(f"/reactions/{rid}/scale", data={"scale": "abc"})
    with app.app_context():
        rxn = db.session.get(Reaction, rid)
        assert rxn.default_scale_mmol == 1.0
