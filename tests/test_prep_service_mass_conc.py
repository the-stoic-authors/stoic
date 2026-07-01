"""Tests for prep_service.suggest_consumptions — mass_concentration strategy.

Covers the use case of dissolving a solid in a solvent to a target g/L
concentration (e.g. NaCl 400 g/L brine solution).
"""

from __future__ import annotations

import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db
from stoic_eln.models.mixture import (
    COMPONENT_ROLE_SOLUTE,
    COMPONENT_ROLE_SOLVENT,
    Mixture,
    MixtureComponent,
)
from stoic_eln.models.substance import Substance
from stoic_eln.services import prep_service


@pytest.fixture
def prep_app():
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app


def _make_brine(concentration_g_per_L: float = 400.0) -> tuple[Mixture, Substance, Substance]:
    """Create a brine mixture: NaCl (solute, g/L) + Water (solvent, no concentration)."""
    nacl = Substance(name="Sodium chloride", molecular_weight=58.44)
    water = Substance(name="Water", molecular_weight=18.02)
    db.session.add_all([nacl, water])
    db.session.flush()

    brine = Mixture(name="Brine", is_active=True)
    db.session.add(brine)
    db.session.flush()

    db.session.add(
        MixtureComponent(
            mixture_id=brine.id,
            substance_id=nacl.id,
            role=COMPONENT_ROLE_SOLUTE,
            concentration=concentration_g_per_L,
            concentration_unit="g/L",
            position=0,
        )
    )
    db.session.add(
        MixtureComponent(
            mixture_id=brine.id,
            substance_id=water.id,
            role=COMPONENT_ROLE_SOLVENT,
            concentration=None,
            concentration_unit=None,
            position=1,
        )
    )
    db.session.commit()
    return brine, nacl, water


def test_mass_concentration_strategy_chosen(prep_app):
    """suggest_consumptions selects mass_concentration strategy for g/L solute."""
    with prep_app.app_context():
        brine, _nacl, _water = _make_brine(400.0)
        result = prep_service.suggest_consumptions(
            mixture=brine,
            target_quantity=1.0,
            target_unit="L",
        )
    # Should not fall back — no "Missing or incompatible" warning
    assert not any("incompatible" in w.lower() or "missing" in w.lower() for w in result.warnings)


def test_mass_concentration_nacl_quantity(prep_app):
    """NaCl quantity = 400 g/L × 1 L = 400 g."""
    with prep_app.app_context():
        brine, nacl, _water = _make_brine(400.0)
        result = prep_service.suggest_consumptions(
            mixture=brine,
            target_quantity=1.0,
            target_unit="L",
        )
    nacl_row = next((r for r in result.rows if r.substance_id == nacl.id), None)
    assert nacl_row is not None
    assert nacl_row.suggested_quantity == pytest.approx(400.0)
    assert nacl_row.suggested_unit == "g"


def test_mass_concentration_solvent_qsp(prep_app):
    """Water (solvent, no concentration) gets target volume as suggested qty."""
    with prep_app.app_context():
        brine, _nacl, water = _make_brine(400.0)
        result = prep_service.suggest_consumptions(
            mixture=brine,
            target_quantity=1.0,
            target_unit="L",
        )
    water_row = next((r for r in result.rows if r.substance_id == water.id), None)
    assert water_row is not None
    assert water_row.suggested_quantity == pytest.approx(1.0)
    assert water_row.suggested_unit == "L"


def test_mass_concentration_scales_with_target(prep_app):
    """For 500 mL target: NaCl = 400 g/L × 0.5 L = 200 g; water = 500 mL."""
    with prep_app.app_context():
        brine, nacl, water = _make_brine(400.0)
        result = prep_service.suggest_consumptions(
            mixture=brine,
            target_quantity=500.0,
            target_unit="mL",
        )
    nacl_row = next((r for r in result.rows if r.substance_id == nacl.id), None)
    water_row = next((r for r in result.rows if r.substance_id == water.id), None)
    assert nacl_row.suggested_quantity == pytest.approx(200.0)
    assert nacl_row.suggested_unit == "g"
    assert water_row.suggested_quantity == pytest.approx(500.0)
    assert water_row.suggested_unit == "mL"
