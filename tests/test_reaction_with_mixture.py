"""Tests for patch 13.5: reactions and runs with mixture-backed components."""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    Mixture,
    MixtureComponent,
    Reaction,
    ReactionComponent,
    Substance,
    User,
)
from stoic_eln.services import run_setup
from stoic_eln.services.reaction_stoich import mmol_from_volume_mL


# ── reaction_stoich.mmol_from_volume_mL ────────────────────────────


def _make_mixture_solution(
    mixture_name: str, solute_name: str, conc: float, unit: str,
    mw: float = 36.46,
):
    """Helper: create a solute substance + mixture with that solute
    at the given concentration."""
    solute = Substance(name=solute_name, molecular_weight=mw)
    water = Substance(name=f"Water-for-{mixture_name}", molecular_weight=18.02)
    db.session.add_all([solute, water]); db.session.flush()
    m = Mixture(name=mixture_name, kind="solution",
                primary_concentration=conc, primary_concentration_unit=unit)
    m.components = [
        MixtureComponent(substance_id=solute.id, role="solute",
                         concentration=conc, concentration_unit=unit, position=0),
        MixtureComponent(substance_id=water.id, role="solvent", position=1),
    ]
    db.session.add(m); db.session.flush()
    return m, solute


def test_mmol_from_volume_normality(app):
    """5 mL of HCl 1N → 5 mmol HCl (monobasic acid: N == M)."""
    with app.app_context():
        m, solute = _make_mixture_solution("HCl 1N", "HCl", 1.0, "N")
        comp = ReactionComponent(
            mixture_id=m.id, role="reagent", equivalents=1.0, position=0,
            reaction_id=None,
        )
        # Need a parent reaction or skip the reaction_id check
        u = User(email="t@t.it", username="t", full_name="t", password_hash="x")
        db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", title="t", status="draft", created_by_id=u.id)
        db.session.add(rxn); db.session.flush()
        comp.reaction_id = rxn.id
        db.session.add(comp); db.session.commit()

        res = mmol_from_volume_mL(comp, 5.0)
        assert res.mmol == pytest.approx(5.0)


def test_mmol_from_volume_molarity(app):
    """10 mL of 0.5 M NaCl → 5 mmol."""
    with app.app_context():
        m, _ = _make_mixture_solution("NaCl 0.5M", "NaCl", 0.5, "M", mw=58.44)
        u = User(email="t@t.it", username="t", full_name="t", password_hash="x")
        rxn = Reaction(code="R", title="t", status="draft", created_by_id=u.id)
        db.session.add_all([u, rxn]); db.session.flush()
        c = ReactionComponent(reaction_id=rxn.id, mixture_id=m.id,
                              role="reagent", equivalents=1.0, position=0)
        db.session.add(c); db.session.commit()
        res = mmol_from_volume_mL(c, 10.0)
        assert res.mmol == pytest.approx(5.0)


def test_mmol_from_volume_mass_per_vol(app):
    """1 mL of 100 mg/mL NaCl → 100 mg / 58.44 = 1.711 mmol."""
    with app.app_context():
        m, _ = _make_mixture_solution(
            "NaCl 100mg/mL", "NaCl", 100.0, "mg/mL", mw=58.44,
        )
        u = User(email="t@t.it", username="t", full_name="t", password_hash="x")
        rxn = Reaction(code="R", title="t", status="draft", created_by_id=u.id)
        db.session.add_all([u, rxn]); db.session.flush()
        c = ReactionComponent(reaction_id=rxn.id, mixture_id=m.id,
                              role="reagent", equivalents=1.0, position=0)
        db.session.add(c); db.session.commit()
        res = mmol_from_volume_mL(c, 1.0)
        assert res.mmol == pytest.approx(100.0 / 58.44, rel=1e-3)


def test_mmol_from_volume_volpct_returns_none(app):
    """%v/v can't be converted without density — explicit fall-through."""
    with app.app_context():
        m, _ = _make_mixture_solution("EtOH 50%", "EtOH", 50.0, "%v/v", mw=46.07)
        u = User(email="t@t.it", username="t", full_name="t", password_hash="x")
        rxn = Reaction(code="R", title="t", status="draft", created_by_id=u.id)
        db.session.add_all([u, rxn]); db.session.flush()
        c = ReactionComponent(reaction_id=rxn.id, mixture_id=m.id,
                              role="reagent", equivalents=1.0, position=0)
        db.session.add(c); db.session.commit()
        res = mmol_from_volume_mL(c, 1.0)
        assert res.mmol is None
        assert "densit" in res.reason


# ── Run integration ────────────────────────────────────────────────


def test_run_target_volume_for_mixture_component(app):
    """Run with a mixture-backed reagent computes target_volume_mL
    = scale × eq / concentration_M.

    HCl 1N (1 M canonical) at 1.2 eq with scale 10 mmol → 12 mL.
    """
    with app.app_context():
        g = Group(name="L", slug="l")
        u = User(email="t@t.it", username="t", full_name="t", password_hash="x")
        sm = Substance(name="SM", molecular_weight=100.0)
        hcl = Substance(name="HCl", molecular_weight=36.46)
        h2o = Substance(name="Water", molecular_weight=18.02)
        prod = Substance(name="Prod", molecular_weight=150.0)
        db.session.add_all([g, u, sm, hcl, h2o, prod]); db.session.flush()

        m_1n = Mixture(name="HCl 1N", kind="solution",
                       primary_concentration=1.0, primary_concentration_unit="N")
        m_1n.components = [
            MixtureComponent(substance_id=hcl.id, role="solute",
                             concentration=1.0, concentration_unit="N", position=0),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_1n); db.session.flush()

        rxn = Reaction(code="R1", title="Salt formation",
                       default_scale_mmol=10.0, status="published",
                       created_by_id=u.id)
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", is_limiting=True,
                              equivalents=1.0, position=0),
            ReactionComponent(reaction_id=rxn.id, mixture_id=m_1n.id,
                              role="reagent", equivalents=1.2, position=1),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=2),
        ])
        db.session.commit()

        run = run_setup.create_draft(rxn, u)
        run.scale_mmol = 10.0
        run_setup.recompute_targets(run)
        db.session.commit()

        hcl_rc = next(
            rc for rc in run.components if rc.mixture_id == m_1n.id
        )
        # 10 mmol × 1.2 / 1 M = 12 mL
        assert hcl_rc.target_volume_mL == pytest.approx(12.0)
        # No mass target (it's a solution, volume only)
        assert hcl_rc.target_mass_g is None


def test_run_template_propagates_mixture_id(app):
    """Creating a draft run from a template carries over mixture_id
    onto the RunComponent."""
    with app.app_context():
        g = Group(name="L", slug="l")
        u = User(email="t@t.it", username="t", full_name="t", password_hash="x")
        sm = Substance(name="SM", molecular_weight=100.0)
        hcl = Substance(name="HCl", molecular_weight=36.46)
        db.session.add_all([g, u, sm, hcl]); db.session.flush()
        m = Mixture(name="HCl 1N", kind="solution",
                    primary_concentration=1.0, primary_concentration_unit="N")
        m.components = [MixtureComponent(substance_id=hcl.id, role="solute",
                                         concentration=1.0, concentration_unit="N",
                                         position=0)]
        db.session.add(m); db.session.flush()
        rxn = Reaction(code="R", title="t", status="published",
                       created_by_id=u.id, default_scale_mmol=5.0)
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", is_limiting=True,
                              equivalents=1.0, position=0),
            ReactionComponent(reaction_id=rxn.id, mixture_id=m.id,
                              role="reagent", equivalents=1.0, position=1),
        ])
        db.session.commit()
        run = run_setup.create_draft(rxn, u)
        db.session.commit()

        kinds = sorted(rc.kind for rc in run.components)
    assert kinds == ["mixture", "substance"]
