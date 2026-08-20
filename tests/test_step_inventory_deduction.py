"""Tests for v1.4.4: step components deduct inventory.

The contract, in one sentence: a step component holds a quantity from a
lot, and every edit moves only the difference — never the whole amount
twice, never nothing at all.

Cases worth pinning down:
  - draft holds nothing (parity with main components, which only move
    stock at Avvia)
  - start_run picks up quantities typed during draft
  - raising, lowering and clearing a quantity move exactly the delta
  - swapping the lot returns to the old one and charges the new one
  - a short lot is clamped at zero and reports the shortfall instead of
    going negative or refusing the entry
  - free entries and unbound components are simply not tracked
"""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_component import ReactionComponent
from stoic_eln.models.run import STATUS_IN_PROGRESS, Run
from stoic_eln.models.run_step import RunStep, RunStepComponent
from stoic_eln.models.substance import Substance
from stoic_eln.models.user import User
from stoic_eln.services import run_setup
from stoic_eln.services.step_inventory import (
    sync_run_step_inventory,
    sync_step_component,
)


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def operator(app):
    with app.app_context():
        u = User(
            username="stepop",
            full_name="Step Op",
            operator_code="SO",
            role="user",
            is_admin=False,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture()
def run_with_step(app, operator):
    """A draft run whose single step has one DCM component + two lots.

    Returns a dict of ids so tests can re-fetch inside their own app
    context without carrying detached instances around.
    """
    with app.app_context():
        sm = Substance(
            name="Acetophenone",
            molecular_formula="C8H8O",
            molecular_weight=120.15,
        )
        prod = Substance(
            name="1-Phenylethanol",
            molecular_formula="C8H10O",
            molecular_weight=122.16,
        )
        dcm = Substance(
            name="DCM",
            molecular_formula="CH2Cl2",
            molecular_weight=84.93,
            state="liquid",
            density=1.33,
        )
        db.session.add_all([sm, prod, dcm])
        db.session.flush()

        sm_lot = InventoryItem(
            substance_id=sm.id,
            batch_code="SM-001",
            quantity_g=100.0,
            initial_quantity_g=100.0,
            is_active=True,
        )
        dcm_lot_a = InventoryItem(
            substance_id=dcm.id,
            batch_code="DCM-A",
            quantity_mL=1000.0,
            initial_quantity_mL=1000.0,
            is_active=True,
        )
        dcm_lot_b = InventoryItem(
            substance_id=dcm.id,
            batch_code="DCM-B",
            quantity_mL=500.0,
            initial_quantity_mL=500.0,
            is_active=True,
        )
        db.session.add_all([sm_lot, dcm_lot_a, dcm_lot_b])
        db.session.flush()

        rxn = Reaction(
            code="RX-2026-0444",
            title="Step deduction rxn",
            status="published",
            template_code="TSD",
        )
        db.session.add(rxn)
        db.session.flush()
        db.session.add_all(
            [
                ReactionComponent(
                    reaction_id=rxn.id,
                    substance_id=sm.id,
                    role="starting_material",
                    is_limiting=True,
                    equivalents=1.0,
                    position=0,
                ),
                ReactionComponent(
                    reaction_id=rxn.id,
                    substance_id=prod.id,
                    role="product",
                    equivalents=1.0,
                    position=1,
                ),
            ]
        )
        db.session.flush()

        user = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, operator=user)
        run.scale_mmol = 10.0
        run_setup.recompute_targets(run)

        step = RunStep(run_id=run.id, title="Estrazione", kind="workup", position=0)
        db.session.add(step)
        db.session.flush()
        sc = RunStepComponent(
            step_id=step.id,
            substance_id=dcm.id,
            role="solvent",
            ratio_kind="free",
            position=0,
        )
        db.session.add(sc)

        # Bind + weigh the main components so the run can actually start.
        for c in run.components:
            if c.role == "starting_material":
                c.inventory_item_id = sm_lot.id
                c.actual_mass_g = 1.2
        db.session.commit()

        return {
            "run": run.id,
            "step_component": sc.id,
            "lot_a": dcm_lot_a.id,
            "lot_b": dcm_lot_b.id,
            "sm_lot": sm_lot.id,
        }


def _start(run_id: int):
    run = db.session.get(Run, run_id)
    results = run_setup.start_run(run)
    db.session.commit()
    return results


# ── draft holds nothing ──────────────────────────────────────────────


def test_draft_does_not_deduct(app, run_with_step):
    """Typing a step quantity in draft is planning, not consumption."""
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 50.0
        res = sync_step_component(sc, active=False)
        db.session.commit()

        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert res is None
        assert lot.quantity_mL == pytest.approx(1000.0)
        assert sc.deducted_volume_mL is None
        assert sc.deducted_lot_id is None


# ── start_run picks up what draft left behind ────────────────────────


def test_start_run_deducts_step_quantities_entered_in_draft(app, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 50.0
        db.session.commit()

        _start(run_with_step["run"])

        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        assert lot.quantity_mL == pytest.approx(950.0)
        assert sc.deducted_volume_mL == pytest.approx(50.0)
        assert sc.deducted_lot_id == run_with_step["lot_a"]


def test_start_run_still_deducts_main_components(app, run_with_step):
    """The new step sync must not disturb the existing behaviour."""
    with app.app_context():
        _start(run_with_step["run"])
        sm_lot = db.session.get(InventoryItem, run_with_step["sm_lot"])
        assert sm_lot.quantity_g == pytest.approx(98.8)


# ── incremental moves while in progress ──────────────────────────────


def _live_component(app_ids):
    """Fetch the step component of an already-started run."""
    sc = db.session.get(RunStepComponent, app_ids["step_component"])
    assert sc.step.run.status == STATUS_IN_PROGRESS
    return sc


def test_increase_deducts_only_the_delta(app, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 50.0
        db.session.commit()
        _start(run_with_step["run"])

        sc = _live_component(run_with_step)
        sc.actual_volume_mL = 80.0
        res = sync_step_component(sc, active=True)
        db.session.commit()

        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert res.deducted == pytest.approx(30.0)
        assert lot.quantity_mL == pytest.approx(920.0)
        assert sc.deducted_volume_mL == pytest.approx(80.0)


def test_correction_downwards_gives_quantity_back(app, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 50.0
        db.session.commit()
        _start(run_with_step["run"])

        sc = _live_component(run_with_step)
        sc.actual_volume_mL = 40.0
        res = sync_step_component(sc, active=True)
        db.session.commit()

        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert res.returned == pytest.approx(10.0)
        assert lot.quantity_mL == pytest.approx(960.0)
        assert sc.deducted_volume_mL == pytest.approx(40.0)


def test_clearing_the_field_returns_everything(app, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 50.0
        db.session.commit()
        _start(run_with_step["run"])

        sc = _live_component(run_with_step)
        sc.actual_volume_mL = None
        res = sync_step_component(sc, active=True)
        db.session.commit()

        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert res.returned == pytest.approx(50.0)
        assert lot.quantity_mL == pytest.approx(1000.0)
        assert sc.deducted_volume_mL is None
        assert sc.deducted_lot_id is None


def test_repeated_sync_is_idempotent(app, run_with_step):
    """Saving the same value twice must not charge the lot twice."""
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 50.0
        db.session.commit()
        _start(run_with_step["run"])

        sc = _live_component(run_with_step)
        assert sync_step_component(sc, active=True) is None
        assert sync_step_component(sc, active=True) is None
        db.session.commit()

        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert lot.quantity_mL == pytest.approx(950.0)


def test_swapping_lot_moves_the_deduction(app, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 50.0
        db.session.commit()
        _start(run_with_step["run"])

        sc = _live_component(run_with_step)
        sc.inventory_item_id = run_with_step["lot_b"]
        sync_step_component(sc, active=True)
        db.session.commit()

        lot_a = db.session.get(InventoryItem, run_with_step["lot_a"])
        lot_b = db.session.get(InventoryItem, run_with_step["lot_b"])
        assert lot_a.quantity_mL == pytest.approx(1000.0)
        assert lot_b.quantity_mL == pytest.approx(450.0)
        assert sc.deducted_lot_id == run_with_step["lot_b"]


def test_switching_unit_moves_channel(app, run_with_step):
    """g → mL on the same lot: the mass is returned, the volume taken."""
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_mass_g = 20.0
        db.session.commit()
        _start(run_with_step["run"])

        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        # The lot has no mass channel, so the whole 20 g falls short.
        assert lot.quantity_mL == pytest.approx(1000.0)

        sc = _live_component(run_with_step)
        sc.actual_mass_g = None
        sc.actual_volume_mL = 25.0
        sync_step_component(sc, active=True)
        db.session.commit()

        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert lot.quantity_mL == pytest.approx(975.0)
        assert sc.deducted_mass_g is None
        assert sc.deducted_volume_mL == pytest.approx(25.0)


# ── short lot: clamp, warn, never refuse ─────────────────────────────


def test_short_lot_is_clamped_and_reports_shortfall(app, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_b"]
        sc.actual_volume_mL = 700.0  # lot B only holds 500
        db.session.commit()
        results = _start(run_with_step["run"])

        lot_b = db.session.get(InventoryItem, run_with_step["lot_b"])
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        assert lot_b.quantity_mL == pytest.approx(0.0)
        assert sc.actual_volume_mL == pytest.approx(700.0)  # the fact stands
        assert sc.deducted_volume_mL == pytest.approx(500.0)  # only what existed
        assert len(results) == 1
        assert results[0].has_shortfall
        assert results[0].shortfall == pytest.approx(200.0)
        assert results[0].lot_label == "DCM-B"


def test_shortfall_does_not_go_negative(app, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_b"]
        sc.actual_volume_mL = 700.0
        db.session.commit()
        _start(run_with_step["run"])

        sc = _live_component(run_with_step)
        sc.actual_volume_mL = 900.0
        sync_step_component(sc, active=True)
        db.session.commit()

        lot_b = db.session.get(InventoryItem, run_with_step["lot_b"])
        assert lot_b.quantity_mL == pytest.approx(0.0)


# ── untracked components ─────────────────────────────────────────────


def test_component_without_lot_is_not_tracked(app, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.actual_volume_mL = 50.0  # no lot bound
        db.session.commit()
        results = _start(run_with_step["run"])

        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        assert results == []
        assert sc.deducted_lot_id is None


def test_free_entry_component_is_ignored(app, run_with_step):
    """A free entry (column diameter, ice…) has no lot and no stock."""
    with app.app_context():
        run = db.session.get(Run, run_with_step["run"])
        step = run.steps[0]
        free = RunStepComponent(
            step_id=step.id,
            free_name="Colonna Ø",
            free_unit="mm",
            role="other",
            ratio_kind="column_diameter_mm",
            position=1,
        )
        db.session.add(free)
        db.session.commit()

        _start(run_with_step["run"])

        free = db.session.get(RunStepComponent, free.id)
        assert free.deducted_lot_id is None


# ── whole-run pass ───────────────────────────────────────────────────


def test_sync_run_is_inert_on_a_draft(app, run_with_step):
    with app.app_context():
        run = db.session.get(Run, run_with_step["run"])
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 50.0
        db.session.commit()

        assert sync_run_step_inventory(run) == []
        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert lot.quantity_mL == pytest.approx(1000.0)


# ── through the web layer (the path Rico actually clicks) ────────────


@pytest.fixture()
def logged_client(app, client, operator):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(operator)
        sess["_fresh"] = True
    return client


def test_route_set_step_actual_deducts_live(app, logged_client, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        db.session.commit()
        _start(run_with_step["run"])

    r = logged_client.post(
        f"/runs/{run_with_step['run']}/step_component/{run_with_step['step_component']}/actual",
        data={"actual": "60", "unit": "mL"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 204

    with app.app_context():
        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert lot.quantity_mL == pytest.approx(940.0)


def test_route_edit_then_correct_moves_only_the_delta(app, logged_client, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        db.session.commit()
        _start(run_with_step["run"])

    url = f"/runs/{run_with_step['run']}/step_component/{run_with_step['step_component']}/actual"
    logged_client.post(url, data={"actual": "60", "unit": "mL"})
    logged_client.post(url, data={"actual": "45", "unit": "mL"})

    with app.app_context():
        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        assert lot.quantity_mL == pytest.approx(955.0)


def test_route_set_step_actual_in_draft_leaves_stock_alone(app, logged_client, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        db.session.commit()

    logged_client.post(
        f"/runs/{run_with_step['run']}/step_component/{run_with_step['step_component']}/actual",
        data={"actual": "60", "unit": "mL"},
    )

    with app.app_context():
        lot = db.session.get(InventoryItem, run_with_step["lot_a"])
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        assert lot.quantity_mL == pytest.approx(1000.0)
        assert sc.actual_volume_mL == pytest.approx(60.0)


def test_route_swap_lot_moves_deduction(app, logged_client, run_with_step):
    with app.app_context():
        sc = db.session.get(RunStepComponent, run_with_step["step_component"])
        sc.inventory_item_id = run_with_step["lot_a"]
        sc.actual_volume_mL = 30.0
        db.session.commit()
        _start(run_with_step["run"])

    r = logged_client.post(
        f"/runs/{run_with_step['run']}/step_component/{run_with_step['step_component']}/lot",
        data={"lot_id": str(run_with_step["lot_b"])},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 204

    with app.app_context():
        lot_a = db.session.get(InventoryItem, run_with_step["lot_a"])
        lot_b = db.session.get(InventoryItem, run_with_step["lot_b"])
        assert lot_a.quantity_mL == pytest.approx(1000.0)
        assert lot_b.quantity_mL == pytest.approx(470.0)


# ── the migration, against an old-schema database ────────────────────


def test_migration_adds_columns_to_old_schema(tmp_path):
    """Empirical check on a table that predates v1.4.4."""
    from sqlalchemy import create_engine, inspect, text

    from stoic_eln.services.schema_migrations import (
        STEP_DEDUCTION_COLUMNS,
        ensure_step_deduction_columns,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE run_step_component ("
                "  id INTEGER PRIMARY KEY,"
                "  step_id INTEGER NOT NULL,"
                "  substance_id INTEGER,"
                "  role VARCHAR(32) NOT NULL,"
                "  actual_volume_mL FLOAT,"
                "  position INTEGER NOT NULL DEFAULT 0"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO run_step_component "
                "(id, step_id, substance_id, role, actual_volume_mL, position) "
                "VALUES (1, 1, 7, 'solvent', 42.0, 0)"
            )
        )

    actions = ensure_step_deduction_columns(engine)
    assert len(actions) == len(STEP_DEDUCTION_COLUMNS)
    assert all("added" in a for a in actions)

    cols = {c["name"] for c in inspect(engine).get_columns("run_step_component")}
    assert set(STEP_DEDUCTION_COLUMNS) <= cols

    # Existing rows survive untouched, with the new columns NULL.
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT actual_volume_mL, deducted_lot_id, deducted_volume_mL "
                "FROM run_step_component WHERE id = 1"
            )
        ).first()
    assert row[0] == pytest.approx(42.0)
    assert row[1] is None and row[2] is None


def test_migration_is_idempotent(tmp_path, app):
    """Second run reports nothing to do — and a fresh DB is already fine."""
    from stoic_eln.services.schema_migrations import ensure_step_deduction_columns

    with app.app_context():
        first = ensure_step_deduction_columns(db.engine)
        second = ensure_step_deduction_columns(db.engine)

    assert all("already present" in a for a in first)  # created by create_all
    assert all("already present" in a for a in second)
