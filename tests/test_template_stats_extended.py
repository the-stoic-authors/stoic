"""Tests for the extended TemplateStats aggregates:

  - avg/min/max/stddev of cost_per_mol of product
  - stddev of yield_percent, cost_eur, cost_per_g

These complement the existing template_stats tests in test_run_setup.py
(aggregation across runs, version grouping, draft exclusion). Here we
focus specifically on the v0.10.0 additions for the Reaction template
report.
"""

from __future__ import annotations

import math

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    InventoryItem,
    Reaction,
    ReactionComponent,
    Substance,
    User,
)
from stoic_eln.services import run_setup
from stoic_eln.services.template_stats import (
    render_sparkline_svg,
    stats_for_template,
)


def _setup_template_with_runs(prod_grams: list[float], template_code: str = "TST"):
    """Build a template (SM → P) and execute one run per prod_g.

    Each run consumes 1 g of SM costing €10/g (so cost_eur = €10).
    The product Substance has MW=200, so each gram of product is
    1/200 mol = 0.005 mol. cost_per_mol = 10 / (prod_g / 200) = 2000 / prod_g.

    Returns the user id (handy for follow-up assertions) — caller must
    be in app_context.
    """
    u = User(
        username="r",
        full_name="R",
        operator_code="RR",
        role="admin",
        is_admin=True,
        is_active=True,
        locale="it",
    )
    u.set_password("x")
    db.session.add(u)
    db.session.flush()

    sm = Substance(name="SM", molecular_weight=100.0)
    prod = Substance(name="P", molecular_weight=200.0)
    db.session.add_all([sm, prod])
    db.session.flush()

    lot = InventoryItem(
        substance_id=sm.id,
        quantity_g=1000.0,
        initial_quantity_g=1000.0,
        total_cost_eur=10000.0,  # → €10/g
        is_active=True,
    )
    db.session.add(lot)
    db.session.flush()

    rxn = Reaction(
        code="RX-" + template_code,
        template_code=f"{template_code}.1",
        template_code_base=template_code,
        version_number=1,
        status="published",
        title="T",
    )
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
                substance_id=prod.id,
                role="product",
                position=1,
            ),
        ]
    )
    db.session.commit()

    for prod_g in prod_grams:
        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0
        run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run)
        db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 1.0
        db.session.commit()
        run_setup.start_run(run)
        db.session.commit()
        cs["product"].actual_mass_g = prod_g
        db.session.commit()
        run_setup.complete_run(run)
        db.session.commit()

    return u.id


# ── €/mol aggregates ────────────────────────────────────────────────


def test_cost_per_mol_aggregates_avg_min_max(app):
    """Three runs producing 0.4 / 0.5 / 0.6 g of product, each costing
    €10. With MW=200, cost_per_mol = 10 / (g/200) = 2000/g.

    Expected: 5000, 4000, 3333.33 €/mol → avg ≈ 4111.11, min ≈ 3333.33,
    max = 5000.
    """
    with app.app_context():
        _setup_template_with_runs([0.4, 0.5, 0.6], template_code="MOL1")
        s = stats_for_template("MOL1")

        assert s.n_runs == 3
        # Each per-run €/mol
        expected = sorted([2000.0 / g for g in [0.4, 0.5, 0.6]])
        assert s.min_cost_per_mol == pytest.approx(expected[0])
        assert s.max_cost_per_mol == pytest.approx(expected[-1])
        assert s.avg_cost_per_mol == pytest.approx(sum(expected) / 3)


def test_cost_per_mol_none_when_no_runs(app):
    """An empty template has all per-mol fields = None."""
    with app.app_context():
        s = stats_for_template("NONEXISTENT")
        assert s.n_runs == 0
        assert s.avg_cost_per_mol is None
        assert s.min_cost_per_mol is None
        assert s.max_cost_per_mol is None
        assert s.stddev_cost_per_mol is None


def test_cost_per_mol_excludes_runs_without_mw(app):
    """If the product substance has no MW, that run contributes to
    n_runs and cost_eur, but NOT to cost_per_mol aggregates (it's
    None for that run)."""
    with app.app_context():
        u = User(
            username="r",
            full_name="R",
            operator_code="RR",
            role="admin",
            is_admin=True,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.flush()

        sm = Substance(name="SM", molecular_weight=100.0)
        # Product with NO MW — €/mol can't be derived
        prod = Substance(name="UNKNOWN", molecular_weight=None)
        db.session.add_all([sm, prod])
        db.session.flush()

        lot = InventoryItem(
            substance_id=sm.id,
            quantity_g=100.0,
            initial_quantity_g=100.0,
            total_cost_eur=1000.0,
            is_active=True,
        )
        db.session.add(lot)
        db.session.flush()

        rxn = Reaction(
            code="RX-NOMW",
            template_code="NOMW.1",
            template_code_base="NOMW",
            version_number=1,
            status="published",
            title="T",
        )
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
                    substance_id=prod.id,
                    role="product",
                    position=1,
                ),
            ]
        )
        db.session.commit()

        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0
        run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run)
        db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 1.0
        db.session.commit()
        run_setup.start_run(run)
        db.session.commit()
        cs["product"].actual_mass_g = 0.5
        db.session.commit()
        run_setup.complete_run(run)
        db.session.commit()

        s = stats_for_template("NOMW")
        assert s.n_runs == 1
        # cost_eur was computable (€10) but cost_per_mol wasn't
        assert s.avg_cost_eur == pytest.approx(10.0)
        assert s.avg_cost_per_mol is None
        assert s.min_cost_per_mol is None


# ── Standard deviation ──────────────────────────────────────────────


def test_stddev_yield_percent_two_runs(app):
    """Two runs with yields 40% and 60% → sample stddev = 14.14..."""
    with app.app_context():
        _setup_template_with_runs([0.4, 0.6], template_code="SD1")
        s = stats_for_template("SD1")
        # yields: 40% (0.4g / theoretical 1g for prod) and 60%
        # avg = 50, sample stddev with n=2 is |x - avg| * sqrt(2) / sqrt(1) → 14.14
        assert s.avg_yield_percent == pytest.approx(50.0)
        assert s.stddev_yield_percent == pytest.approx(math.sqrt(200.0))


def test_stddev_none_with_single_run(app):
    """A single run has no spread → all stddev fields None."""
    with app.app_context():
        _setup_template_with_runs([0.5], template_code="SD2")
        s = stats_for_template("SD2")
        assert s.n_runs == 1
        assert s.stddev_yield_percent is None
        assert s.stddev_cost_eur is None
        assert s.stddev_cost_per_g is None
        assert s.stddev_cost_per_mol is None


def test_stddev_zero_with_identical_runs(app):
    """Two runs with identical yields → sample stddev = 0."""
    with app.app_context():
        _setup_template_with_runs([0.5, 0.5], template_code="SD3")
        s = stats_for_template("SD3")
        assert s.stddev_yield_percent == pytest.approx(0.0)
        assert s.stddev_cost_eur == pytest.approx(0.0)


def test_stddev_cost_eur_and_per_g(app):
    """stddev for cost € and cost €/g compute correctly across multiple runs.

    Three runs with yields 0.4/0.5/0.6 g → each run cost €10 (same SM
    consumption), so stddev_cost_eur = 0. cost_per_g varies inversely
    with yield_g: 25, 20, 16.67."""
    with app.app_context():
        _setup_template_with_runs([0.4, 0.5, 0.6], template_code="SD4")
        s = stats_for_template("SD4")
        # cost_eur is identical across runs → stddev = 0
        assert s.stddev_cost_eur == pytest.approx(0.0)
        # cost_per_g varies → non-zero stddev
        cpgs = [10.0 / g for g in [0.4, 0.5, 0.6]]  # 25, 20, 16.67
        import statistics

        expected_sd = statistics.stdev(cpgs)
        assert s.stddev_cost_per_g == pytest.approx(expected_sd, rel=1e-3)


# ── Sparkline supports cost_per_mol ────────────────────────────────


def test_sparkline_renders_for_cost_per_mol(app):
    with app.app_context():
        _setup_template_with_runs([0.4, 0.5, 0.6], template_code="SPM")
        s = stats_for_template("SPM")
        svg = render_sparkline_svg(s.points, metric="cost_per_mol", width=600, height=140)
        assert svg.startswith("<svg")
        assert "path" in svg


def test_sparkline_unknown_metric_returns_empty(app):
    with app.app_context():
        _setup_template_with_runs([0.4, 0.5], template_code="SPN")
        s = stats_for_template("SPN")
        svg = render_sparkline_svg(s.points, metric="banana")
        assert svg == ""
