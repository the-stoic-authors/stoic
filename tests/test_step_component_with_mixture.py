"""Tests for patch 13.6 — step components support mixtures and
the 'free volume' ratio_kind (chromatography eluent use case)."""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    InventoryItem,
    Mixture,
    MixtureComponent,
    Reaction,
    ReactionComponent,
    ReactionStep,
    ReactionStepComponent,
    Substance,
    User,
)
from stoic_eln.models.run_step import RunStepComponent
from stoic_eln.services import run_setup


def _bootstrap(app):
    """Common fixture: user, group, basic substances, a published
    template reaction with a chromatography step using EtOAc/PE 5:2.

    Returns a dict of IDs (not ORM instances) to avoid detached-
    instance errors in tests that open their own app_context.
    """
    with app.app_context():
        g = Group(name="Lab", slug="lab")
        u = User(email="t@t.it", username="t", full_name="t", password_hash="x")
        sm = Substance(name="SM", molecular_weight=100.0, state="solid")
        etoac = Substance(name="EtOAc", molecular_weight=88.11, state="liquid",
                          density=0.902)
        pe = Substance(name="PE", molecular_weight=86.18, state="liquid",
                       density=0.66)
        db.session.add_all([g, u, sm, etoac, pe]); db.session.flush()

        eluent = Mixture(name="EtOAc/PE 5:2", kind="eluent")
        eluent.components = [
            MixtureComponent(substance_id=etoac.id, role="cosolvent",
                             concentration=5.0, concentration_unit="ratio",
                             position=0),
            MixtureComponent(substance_id=pe.id, role="cosolvent",
                             concentration=2.0, concentration_unit="ratio",
                             position=1),
        ]
        db.session.add(eluent); db.session.flush()

        rxn = Reaction(code="R-chromo", title="Test chromato",
                       default_scale_mmol=5.0, status="published",
                       created_by_id=u.id)
        db.session.add(rxn); db.session.flush()
        db.session.add(ReactionComponent(
            reaction_id=rxn.id, substance_id=sm.id,
            role="starting_material", is_limiting=True,
            equivalents=1.0, position=0,
        ))
        step = ReactionStep(
            reaction_id=rxn.id, title="Cromatografia",
            description="Eluire con EtOAc/PE 5:2",
            kind="purification", position=0,
        )
        db.session.add(step); db.session.flush()
        sc = ReactionStepComponent(
            step_id=step.id, mixture_id=eluent.id,
            role="solvent", ratio_kind="free", ratio_value=None,
            position=0,
        )
        db.session.add(sc); db.session.flush()

        lot_eluent = InventoryItem(
            mixture_id=eluent.id, group_id=g.id,
            batch_code="ETOACPE52-001",
            quantity_mL=1500.0, initial_quantity_mL=1500.0,
            is_active=True,
        )
        lot_sm = InventoryItem(
            substance_id=sm.id, group_id=g.id, batch_code="SM-001",
            quantity_g=10.0, initial_quantity_g=10.0, is_active=True,
        )
        db.session.add_all([lot_eluent, lot_sm]); db.session.commit()

        return {
            "user_id": u.id, "group_id": g.id,
            "sm_id": sm.id, "eluent_id": eluent.id,
            "reaction_id": rxn.id, "step_id": step.id,
            "step_component_id": sc.id,
            "lot_eluent_id": lot_eluent.id, "lot_sm_id": lot_sm.id,
        }


def test_step_component_can_be_mixture_backed(app):
    """A ReactionStepComponent can point at a Mixture via XOR check."""
    fx = _bootstrap(app)
    with app.app_context():
        sc = db.session.get(ReactionStepComponent, fx["step_component_id"])
        assert sc is not None
        assert sc.kind == "mixture"
        assert sc.mixture_id == fx["eluent_id"]
        assert sc.substance_id is None
        assert sc.display_name == "EtOAc/PE 5:2"
        assert sc.is_free_volume is True


def test_step_component_free_ratio_kind(app):
    """The 'free' ratio_kind means no value at template time."""
    fx = _bootstrap(app)
    with app.app_context():
        sc = db.session.get(ReactionStepComponent, fx["step_component_id"])
        assert sc.ratio_kind == "free"
        assert sc.ratio_value is None
        assert sc.is_free_volume

        sc.ratio_kind = "absolute_mL"
        sc.ratio_value = 250.0
        db.session.commit()
        db.session.refresh(sc)
        assert sc.is_free_volume is False


def test_step_component_propagates_to_run(app):
    """create_draft copies mixture_id from reaction step component to
    run step component."""
    fx = _bootstrap(app)
    with app.app_context():
        rxn = db.session.get(Reaction, fx["reaction_id"])
        user = db.session.get(User, fx["user_id"])
        run = run_setup.create_draft(rxn, user)
        db.session.commit()

        assert len(run.steps) == 1
        run_step = run.steps[0]
        assert len(run_step.components) == 1
        rsc = run_step.components[0]
        assert rsc.kind == "mixture"
        assert rsc.mixture_id == fx["eluent_id"]
        assert rsc.substance_id is None
        assert rsc.ratio_kind == "free"
        assert rsc.display_name == "EtOAc/PE 5:2"


def test_run_step_component_records_actual_volume_for_free_eluent(app):
    """The whole point of 'free' kind: at run time the operator types
    the actual mL of eluent used."""
    fx = _bootstrap(app)
    with app.app_context():
        rxn = db.session.get(Reaction, fx["reaction_id"])
        user = db.session.get(User, fx["user_id"])
        run = run_setup.create_draft(rxn, user)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)
        db.session.commit()

        rsc = run.steps[0].components[0]
        # Free kind → no template target
        assert rsc.target_volume_mL is None
        assert rsc.target_mass_g is None

        rsc.actual_volume_mL = 350.0
        rsc.inventory_item_id = fx["lot_eluent_id"]
        db.session.commit()

        db.session.refresh(rsc)
        assert rsc.actual_volume_mL == pytest.approx(350.0)
        assert rsc.inventory_item.batch_code == "ETOACPE52-001"


def test_step_quantity_skips_free_kind(app):
    """The _step_quantity helper returns all-None for free components
    so the template renders 'ad lib.' instead of a number."""
    from stoic_eln import _step_quantity
    fx = _bootstrap(app)
    with app.app_context():
        rxn = db.session.get(Reaction, fx["reaction_id"])
        sc = rxn.steps[0].components[0]
        result = _step_quantity(sc, rxn.steps[0], rxn)
        assert result == {"g": None, "mL": None, "mmol": None}


def test_step_component_xor_constraint(app):
    """Setting both substance_id and mixture_id violates XOR."""
    with app.app_context():
        from sqlalchemy.exc import IntegrityError
        g = Group(name="L", slug="l")
        sub = Substance(name="X", molecular_weight=100.0)
        mix = Mixture(name="Y", kind="solution")
        db.session.add_all([g, sub, mix]); db.session.flush()

        u = User(email="t@t.it", username="t", full_name="t", password_hash="x")
        db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", title="t", status="draft", created_by_id=u.id)
        db.session.add(rxn); db.session.flush()
        step = ReactionStep(reaction_id=rxn.id, title="s", kind="reaction",
                            position=0)
        db.session.add(step); db.session.flush()

        bad = ReactionStepComponent(
            step_id=step.id,
            substance_id=sub.id, mixture_id=mix.id,  # both set → violates XOR
            role="solvent", ratio_kind="eq", ratio_value=1.0, position=0,
        )
        db.session.add(bad)
        with pytest.raises(IntegrityError):
            db.session.commit()


# ── Regression: clone_for_editing must carry mixture_id over ────


def test_clone_for_editing_preserves_step_component_mixture_id(app):
    """Regression for bug found in 14.6.1: ``clone_for_editing`` only
    copied ``substance_id`` from each ``ReactionStepComponent``,
    silently dropping ``mixture_id``. The resulting clone violated
    the substance-xor-mixture CHECK constraint at flush time, raising
    ``IntegrityError``.

    Reproduction: published reaction with a step that uses an eluent
    (a Mixture) as its solvent — exactly the chromatography use case
    the 13.6 patch was built for. Cloning that reaction for editing
    must succeed, and the cloned step component must keep the
    ``mixture_id`` (and a NULL ``substance_id``).
    """
    from stoic_eln.services import reaction_clone

    with app.app_context():
        g = Group(slug="lab", name="lab")
        sub_sm = Substance(name="SM", molecular_weight=100.0)
        sub_eluent_a = Substance(name="EtOAc", molecular_weight=88.1)
        sub_eluent_b = Substance(name="PE", molecular_weight=86.2)
        db.session.add_all([g, sub_sm, sub_eluent_a, sub_eluent_b])
        db.session.flush()

        eluent = Mixture(name="EtOAc/PE 5:2", kind="eluent")
        eluent.components = [
            MixtureComponent(substance_id=sub_eluent_a.id, role="solvent",
                             position=0),
            MixtureComponent(substance_id=sub_eluent_b.id, role="solvent",
                             position=1),
        ]
        db.session.add(eluent); db.session.flush()

        u = User(email="rico@lab.it", username="rico",
                 full_name="Rico", password_hash="x")
        db.session.add(u); db.session.flush()

        rxn = Reaction(
            code="CLONE-MIX", title="Cloneable",
            template_code="CLM.1", template_code_base="CLM",
            version_number=1, status="published",
            default_scale_mmol=1.0, created_by_id=u.id,
        )
        db.session.add(rxn); db.session.flush()
        db.session.add(ReactionComponent(
            reaction_id=rxn.id, substance_id=sub_sm.id,
            role="starting_material", position=0,
            is_limiting=True, equivalents=1.0,
        ))
        # Chromatography purification step with a mixture-based eluent
        step = ReactionStep(
            reaction_id=rxn.id, title="Column chromatography",
            kind="purification", position=0,
        )
        db.session.add(step); db.session.flush()
        db.session.add(ReactionStepComponent(
            step_id=step.id,
            substance_id=None,  # ← XOR with mixture_id
            mixture_id=eluent.id,
            role="solvent", ratio_kind="mL_per_mmol",
            ratio_value=10.0, position=0,
        ))
        db.session.commit()

        # Act — this used to raise IntegrityError before the fix
        draft = reaction_clone.clone_for_editing(rxn, created_by_id=u.id)
        db.session.commit()

        # Assert — draft has the step component, with mixture_id preserved
        assert draft.status == "draft"
        assert len(draft.steps) == 1
        cloned_step = draft.steps[0]
        assert len(cloned_step.components) == 1
        cloned_sc = cloned_step.components[0]
        assert cloned_sc.substance_id is None
        assert cloned_sc.mixture_id == eluent.id
        assert cloned_sc.role == "solvent"
        assert cloned_sc.ratio_kind == "mL_per_mmol"
        assert cloned_sc.ratio_value == 10.0


def test_clone_for_editing_preserves_step_component_substance_id(app):
    """Companion test: when a step component uses a Substance (not a
    Mixture), the clone must keep ``substance_id`` set and
    ``mixture_id`` NULL. Guards against accidentally over-fixing the
    bug by always populating ``mixture_id``.
    """
    from stoic_eln.services import reaction_clone

    with app.app_context():
        g = Group(slug="lab2", name="lab2")
        sub_sm = Substance(name="SM2", molecular_weight=100.0)
        sub_solvent = Substance(name="DCM", molecular_weight=84.93)
        db.session.add_all([g, sub_sm, sub_solvent]); db.session.flush()

        u = User(email="rico2@lab.it", username="rico2",
                 full_name="Rico", password_hash="x")
        db.session.add(u); db.session.flush()

        rxn = Reaction(
            code="CLONE-SUB", title="Cloneable sub",
            template_code="CLS.1", template_code_base="CLS",
            version_number=1, status="published",
            default_scale_mmol=1.0, created_by_id=u.id,
        )
        db.session.add(rxn); db.session.flush()
        db.session.add(ReactionComponent(
            reaction_id=rxn.id, substance_id=sub_sm.id,
            role="starting_material", position=0,
            is_limiting=True, equivalents=1.0,
        ))
        step = ReactionStep(
            reaction_id=rxn.id, title="Workup",
            kind="workup", position=0,
        )
        db.session.add(step); db.session.flush()
        db.session.add(ReactionStepComponent(
            step_id=step.id,
            substance_id=sub_solvent.id,
            mixture_id=None,
            role="solvent", ratio_kind="mL_per_mmol",
            ratio_value=5.0, position=0,
        ))
        db.session.commit()

        draft = reaction_clone.clone_for_editing(rxn, created_by_id=u.id)
        db.session.commit()

        cloned_sc = draft.steps[0].components[0]
        assert cloned_sc.substance_id == sub_solvent.id
        assert cloned_sc.mixture_id is None
        assert cloned_sc.role == "solvent"
