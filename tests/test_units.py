"""Tests for stoic_eln.services.units."""

from __future__ import annotations

import pytest

from stoic_eln.services import units


# ── best_fit_mass ────────────────────────────────────────────────────────


def test_best_fit_mass_below_1g_uses_mg():
    fa = units.best_fit_mass(0.5)
    assert fa.unit == "mg"
    assert fa.value == pytest.approx(500.0)
    assert fa.formatted == "500.000"


def test_best_fit_mass_at_1g_uses_g():
    fa = units.best_fit_mass(1.0)
    assert fa.unit == "g"
    assert fa.formatted == "1.000"


def test_best_fit_mass_above_1g_uses_g():
    fa = units.best_fit_mass(127.3)
    assert fa.unit == "g"
    assert fa.formatted == "127.300"


def test_best_fit_mass_3_decimals_with_trailing_zeros():
    fa = units.best_fit_mass(0.1)
    assert fa.formatted == "100.000"


def test_best_fit_mass_none():
    assert units.best_fit_mass(None) is None


# ── best_fit_volume ──────────────────────────────────────────────────────


def test_best_fit_volume_below_1L_uses_mL():
    fa = units.best_fit_volume(8.33)
    assert fa.unit == "mL"
    assert fa.formatted == "8.330"


def test_best_fit_volume_at_1L_uses_L():
    fa = units.best_fit_volume(1000.0)
    assert fa.unit == "L"
    assert fa.formatted == "1.000"


def test_best_fit_volume_above_1L_uses_L():
    fa = units.best_fit_volume(2500.0)
    assert fa.unit == "L"
    assert fa.formatted == "2.500"


# ── parse_scale_to_mmol ──────────────────────────────────────────────────


def test_parse_scale_mmol_passthrough():
    assert units.parse_scale_to_mmol(5.0, "mmol") == 5.0


def test_parse_scale_mol_to_mmol():
    assert units.parse_scale_to_mmol(0.005, "mol") == pytest.approx(5.0)


def test_parse_scale_mass_uses_mw(app):
    """500 mg of MW=100 → 5 mmol."""
    with app.app_context():
        from stoic_eln.models.substance import Substance
        from stoic_eln.extensions import db

        sub = Substance(name="X", molecular_weight=100.0)
        db.session.add(sub)
        db.session.commit()
        assert units.parse_scale_to_mmol(500, "mg", substance=sub) == pytest.approx(5.0)
        assert units.parse_scale_to_mmol(0.5, "g", substance=sub) == pytest.approx(5.0)


def test_parse_scale_volume_uses_density_and_mw(app):
    """For a liquid with density=0.9 g/mL and MW=46, 1 mL → 19.57 mmol."""
    with app.app_context():
        from stoic_eln.models.substance import Substance
        from stoic_eln.extensions import db

        sub = Substance(name="EtOH", molecular_weight=46.07, density=0.789, state="liquid")
        db.session.add(sub)
        db.session.commit()
        # 1 mL × 0.789 g/mL = 0.789 g = 0.789/46.07 × 1000 = 17.13 mmol
        assert units.parse_scale_to_mmol(1.0, "mL", substance=sub) == pytest.approx(17.13, abs=0.05)


def test_parse_scale_mass_without_mw_raises(app):
    with app.app_context():
        from stoic_eln.models.substance import Substance
        from stoic_eln.extensions import db

        sub = Substance(name="Y", molecular_weight=None)
        db.session.add(sub)
        db.session.commit()
        with pytest.raises(units.ScaleConversionError):
            units.parse_scale_to_mmol(500, "mg", substance=sub)


def test_parse_scale_volume_without_density_raises(app):
    with app.app_context():
        from stoic_eln.models.substance import Substance
        from stoic_eln.extensions import db

        sub = Substance(name="Y", molecular_weight=46.0, density=None)
        db.session.add(sub)
        db.session.commit()
        with pytest.raises(units.ScaleConversionError):
            units.parse_scale_to_mmol(1.0, "mL", substance=sub)


# ── recompute_targets with liquid reagents ──────────────────────────────


def test_recompute_targets_liquid_reagent_uses_volume(app):
    """A liquid reagent with density should get target_volume_mL not _mass_g."""
    from stoic_eln.extensions import db
    from stoic_eln.models.reaction import Reaction
    from stoic_eln.models.reaction_component import ReactionComponent
    from stoic_eln.models.substance import Substance
    from stoic_eln.services import run_setup

    with app.app_context():
        # Limiting solid SM
        sm = Substance(name="SM", molecular_weight=100.0, state="solid")
        # Liquid co-reagent with density
        liq = Substance(name="Aniline", molecular_weight=93.13, density=1.022, state="liquid")
        prod = Substance(name="Prod", molecular_weight=200.0)
        db.session.add_all([sm, liq, prod])
        db.session.flush()

        rxn = Reaction(code="RX", template_code="T", status="published", title="T")
        db.session.add(rxn)
        db.session.flush()
        db.session.add_all(
            [
                ReactionComponent(
                    reaction_id=rxn.id,
                    substance_id=sm.id,
                    role="starting_material",
                    position=0,
                    is_limiting=True,
                    equivalents=1.0,
                ),
                ReactionComponent(
                    reaction_id=rxn.id,
                    substance_id=liq.id,
                    role="reagent",
                    position=1,
                    equivalents=1.0,
                ),
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=prod.id, role="product", position=2
                ),
            ]
        )
        db.session.commit()

        from stoic_eln.models.user import User

        u = User(
            username="op",
            full_name="Op",
            operator_code="OP",
            role="user",
            is_admin=False,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.commit()

        run = run_setup.create_draft(rxn, u)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)

        sm_comp = next(c for c in run.components if c.substance_id == sm.id)
        liq_comp = next(c for c in run.components if c.substance_id == liq.id)

        # SM (solid): mass target
        assert sm_comp.target_mass_g is not None
        assert sm_comp.target_volume_mL is None
        # Liquid: volume target
        assert liq_comp.target_mass_g is None
        assert liq_comp.target_volume_mL is not None
        # 5 mmol × 93.13/1000 g / 1.022 g/mL = 0.4556 mL
        assert liq_comp.target_volume_mL == pytest.approx(0.4556, abs=0.001)
