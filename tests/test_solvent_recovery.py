"""Tests for v1.5.0: solvent recovery from run steps.

The contract: recovering from a step creates a lot whose composition
reflects only the components the operator ticked, whose catalogue entry
is shared with every other recovery that rounds the same way, and whose
use counter follows the worst source.

The case that drives the design is the extraction step: DCM plus water,
where only the DCM is kept. If the composition were inferred from "all
solvents in the step", that lot would claim to be DCM/water — a bottle
that exists nowhere and would come back to poison a later column.
"""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.mixture import Mixture
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_component import ReactionComponent
from stoic_eln.models.run import Run
from stoic_eln.models.run_step import RunStep, RunStepComponent
from stoic_eln.models.substance import Substance
from stoic_eln.models.user import User
from stoic_eln.services import run_setup
from stoic_eln.services.solvent_recovery import (
    RecoveryError,
    is_default_ticked,
    recoverable_components,
    register_recovery,
)


@pytest.fixture()
def lab(app):
    """A started run with one purification step: EtOAc, hexane, water.

    Water is in the step on purpose — it is the component that must
    never end up in a recovered lot unless explicitly ticked.
    """
    with app.app_context():
        u = User(
            username="recop",
            full_name="Rec Op",
            operator_code="RO",
            role="user",
            is_admin=False,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)

        sm = Substance(name="Substrate", molecular_formula="C8H8O", molecular_weight=120.15)
        prod = Substance(name="Product", molecular_formula="C8H10O", molecular_weight=122.16)
        etoac = Substance(
            name="EtOAc",
            molecular_formula="C4H8O2",
            molecular_weight=88.11,
            state="liquid",
            density=0.902,
        )
        hexane = Substance(
            name="Esano",
            molecular_formula="C6H14",
            molecular_weight=86.18,
            state="liquid",
            density=0.659,
        )
        water = Substance(
            name="Acqua",
            molecular_formula="H2O",
            molecular_weight=18.02,
            state="liquid",
            density=1.0,
        )
        db.session.add_all([sm, prod, etoac, hexane, water])
        db.session.flush()

        lots = {}
        for key, sub, vol in (
            ("etoac", etoac, 2000.0),
            ("hexane", hexane, 2000.0),
            ("water", water, 5000.0),
        ):
            lot = InventoryItem(
                substance_id=sub.id,
                batch_code=f"{key.upper()}-1",
                quantity_mL=vol,
                initial_quantity_mL=vol,
                is_active=True,
            )
            db.session.add(lot)
            lots[key] = lot
        sm_lot = InventoryItem(
            substance_id=sm.id,
            batch_code="SM-1",
            quantity_g=100.0,
            initial_quantity_g=100.0,
            is_active=True,
        )
        db.session.add(sm_lot)
        db.session.flush()

        rxn = Reaction(
            code="RX-2026-0500", title="Recovery rxn", status="published", template_code="TREC"
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

        run = run_setup.create_draft(rxn, operator=u)
        run.scale_mmol = 10.0
        run_setup.recompute_targets(run)
        for c in run.components:
            if c.role == "starting_material":
                c.inventory_item_id = sm_lot.id
                c.actual_mass_g = 1.2

        step = RunStep(run_id=run.id, title="Colonna", kind="purification", position=0)
        db.session.add(step)
        db.session.flush()

        comps = {}
        for pos, (key, sub, role) in enumerate(
            (
                ("etoac", etoac, "solvent"),
                ("hexane", hexane, "solvent"),
                ("water", water, "other"),
            )
        ):
            sc = RunStepComponent(
                step_id=step.id,
                substance_id=sub.id,
                role=role,
                ratio_kind="free",
                position=pos,
                inventory_item_id=lots[key].id,
            )
            db.session.add(sc)
            comps[key] = sc
        db.session.commit()

        run_setup.start_run(run)
        db.session.commit()

        return {
            "run": run.id,
            "step": step.id,
            "user": u.id,
            "c_etoac": comps["etoac"].id,
            "c_hexane": comps["hexane"].id,
            "c_water": comps["water"].id,
            "l_etoac": lots["etoac"].id,
            "l_hexane": lots["hexane"].id,
        }


def _set_volumes(lab, etoac=None, hexane=None, water=None):
    from stoic_eln.services.step_inventory import sync_step_component

    for cid, vol in (
        (lab["c_etoac"], etoac),
        (lab["c_hexane"], hexane),
        (lab["c_water"], water),
    ):
        if vol is None:
            continue
        sc = db.session.get(RunStepComponent, cid)
        sc.actual_volume_mL = vol
        sync_step_component(sc, active=True)
    db.session.commit()


# ── candidates ───────────────────────────────────────────────────────


def test_candidates_do_not_depend_on_recorded_quantities(app, lab):
    """Regression, v1.5.1.

    The first cut required a recorded volume, which made the whole
    recovery section vanish from a step where nothing had been typed
    yet — silently, because the template hides an empty candidate list.
    Worse, the original version of this test asserted the empty list as
    if it were correct, so the suite documented the bug instead of
    catching it.
    """
    with app.app_context():
        step = db.session.get(RunStep, lab["step"])
        names = {sc.substance.name for sc in recoverable_components(step)}
        assert names == {"EtOAc", "Esano", "Acqua"}

        _set_volumes(lab, etoac=200.0, hexane=800.0)
        step = db.session.get(RunStep, lab["step"])
        assert len(recoverable_components(step)) == 3


def test_water_is_offered_but_not_pre_ticked(app, lab):
    """Water is a legitimate choice — just never a default one."""
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0, water=500.0)
        step = db.session.get(RunStep, lab["step"])
        by_name = {sc.substance.name: sc for sc in recoverable_components(step)}
        assert "Acqua" in by_name
        assert is_default_ticked(by_name["Acqua"]) is False
        assert is_default_ticked(by_name["EtOAc"]) is True


def test_free_entry_is_not_a_candidate(app, lab):
    with app.app_context():
        step = db.session.get(RunStep, lab["step"])
        db.session.add(
            RunStepComponent(
                step_id=step.id,
                free_name="Colonna Ø",
                free_unit="mm",
                role="other",
                ratio_kind="column_diameter_mm",
                position=9,
            )
        )
        db.session.commit()
        _set_volumes(lab, etoac=200.0)
        step = db.session.get(RunStep, lab["step"])
        assert all(sc.substance_id is not None for sc in recoverable_components(step))


# ── composition ──────────────────────────────────────────────────────


def test_two_components_give_a_mixture_lot_rounded_to_10pct(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=190.0, hexane=810.0)  # 19:81 → 20:80
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 700.0, user_id=lab["user"])
        db.session.commit()

        assert res.lot.mixture_id is not None
        assert res.lot.substance_id is None
        assert res.lot.quantity_mL == pytest.approx(700.0)
        pcts = sorted(c.concentration for c in res.mixture.components)
        assert pcts == [20.0, 80.0]
        assert all(c.concentration_unit == "%v/v" for c in res.mixture.components)


def test_single_component_gives_a_substance_lot(app, lab):
    """An extraction with DCM alone: no catalogue entry needed."""
    with app.app_context():
        _set_volumes(lab, etoac=300.0)
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"]], 250.0, user_id=lab["user"])
        db.session.commit()

        assert res.mixture is None
        assert res.lot.mixture_id is None
        assert res.lot.substance_id is not None
        assert res.lot.is_recovered is True


def test_unticked_water_never_enters_the_composition(app, lab):
    """The case the whole design exists for."""
    with app.app_context():
        _set_volumes(lab, etoac=500.0, hexane=500.0, water=1000.0)
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 600.0, user_id=lab["user"])
        db.session.commit()

        substance_ids = {c.substance_id for c in res.mixture.components}
        water_id = db.session.get(RunStepComponent, lab["c_water"]).substance_id
        assert water_id not in substance_ids
        assert len(substance_ids) == 2


# ── catalogue dedup ──────────────────────────────────────────────────


def test_same_rounded_composition_reuses_the_catalogue_entry(app, lab):
    """95:5 and 92:8 are the same bottle as far as the shelf cares."""
    with app.app_context():
        before = db.session.query(Mixture).count()

        _set_volumes(lab, etoac=50.0, hexane=950.0)  # 5:95 → 0:100 → single
        _set_volumes(lab, etoac=120.0, hexane=880.0)  # 12:88 → 10:90
        step = db.session.get(RunStep, lab["step"])
        first = register_recovery(
            step, [lab["c_etoac"], lab["c_hexane"]], 400.0, user_id=lab["user"]
        )
        db.session.commit()

        _set_volumes(lab, etoac=80.0, hexane=920.0)  # 8:92 → 10:90 as well
        step = db.session.get(RunStep, lab["step"])
        second = register_recovery(
            step, [lab["c_etoac"], lab["c_hexane"]], 300.0, user_id=lab["user"]
        )
        db.session.commit()

        assert first.mixture.id == second.mixture.id
        assert second.reused_catalogue_entry is True
        assert db.session.query(Mixture).count() == before + 1
        assert first.lot.id != second.lot.id


def test_different_composition_creates_a_second_entry(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0)  # 20:80
        step = db.session.get(RunStep, lab["step"])
        a = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 400.0, user_id=lab["user"])
        db.session.commit()

        _set_volumes(lab, etoac=600.0, hexane=400.0)  # 60:40
        step = db.session.get(RunStep, lab["step"])
        b = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 400.0, user_id=lab["user"])
        db.session.commit()

        assert a.mixture.id != b.mixture.id


def test_percentages_always_sum_to_100(app, lab):
    """Three equal parts round to 30/30/30; the largest absorbs the rest."""
    with app.app_context():
        _set_volumes(lab, etoac=333.0, hexane=333.0, water=334.0)
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(
            step,
            [lab["c_etoac"], lab["c_hexane"], lab["c_water"]],
            900.0,
            user_id=lab["user"],
        )
        db.session.commit()
        assert sum(s.percent for s in res.shares) == pytest.approx(100.0)
        assert sum(c.concentration for c in res.mixture.components) == pytest.approx(100.0)


# ── use counter: worst case ──────────────────────────────────────────


def test_fresh_sources_give_use_count_one(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0)
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 700.0, user_id=lab["user"])
        db.session.commit()
        assert res.use_count == 1
        assert res.lot.recovery_use_count == 1


def test_use_count_follows_the_worst_source(app, lab):
    """0 uses + 2 uses → 3, not an average."""
    with app.app_context():
        hexane_lot = db.session.get(InventoryItem, lab["l_hexane"])
        hexane_lot.is_recovered = True
        hexane_lot.recovery_use_count = 2
        db.session.commit()

        _set_volumes(lab, etoac=900.0, hexane=100.0)  # hexane is the minority
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 700.0, user_id=lab["user"])
        db.session.commit()
        assert res.use_count == 3


# ── provenance and constraints ───────────────────────────────────────


def test_lot_carries_provenance_and_reuse_constraint(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0)
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 700.0, user_id=lab["user"])
        db.session.commit()

        run = db.session.get(Run, lab["run"])
        assert res.lot.source_run_id == run.id
        assert res.lot.recovered_from_step_id == lab["step"]
        assert res.lot.origin_reaction_id == run.reaction_id
        assert res.lot.recovered_at is not None
        assert res.lot.batch_code == f"{run.code}-REC1"


def test_batch_codes_increment_within_a_run(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0)
        step = db.session.get(RunStep, lab["step"])
        first = register_recovery(step, [lab["c_etoac"]], 100.0, user_id=lab["user"])
        db.session.commit()
        step = db.session.get(RunStep, lab["step"])
        second = register_recovery(step, [lab["c_hexane"]], 100.0, user_id=lab["user"])
        db.session.commit()

        run = db.session.get(Run, lab["run"])
        assert first.lot.batch_code == f"{run.code}-REC1"
        assert second.lot.batch_code == f"{run.code}-REC2"


def test_recovered_lot_inherits_the_group_of_its_sources(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0)
        source = db.session.get(InventoryItem, lab["l_etoac"])
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 700.0, user_id=lab["user"])
        db.session.commit()
        assert res.lot.group_id == source.group_id


# ── refusals ─────────────────────────────────────────────────────────


def test_zero_volume_is_refused(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0)
        step = db.session.get(RunStep, lab["step"])
        with pytest.raises(RecoveryError):
            register_recovery(step, [lab["c_etoac"]], 0.0, user_id=lab["user"])


def test_no_components_selected_is_refused(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0)
        step = db.session.get(RunStep, lab["step"])
        with pytest.raises(RecoveryError):
            register_recovery(step, [], 100.0, user_id=lab["user"])


def test_component_from_another_step_is_refused(app, lab):
    with app.app_context():
        run = db.session.get(Run, lab["run"])
        other = RunStep(run_id=run.id, title="Altro", kind="workup", position=1)
        db.session.add(other)
        db.session.flush()
        stray = RunStepComponent(
            step_id=other.id,
            substance_id=db.session.get(RunStepComponent, lab["c_etoac"]).substance_id,
            role="solvent",
            ratio_kind="free",
            position=0,
            actual_volume_mL=50.0,
        )
        db.session.add(stray)
        db.session.commit()

        _set_volumes(lab, etoac=200.0)
        step = db.session.get(RunStep, lab["step"])
        with pytest.raises(RecoveryError):
            register_recovery(step, [stray.id], 100.0, user_id=lab["user"])


# ── the migration ────────────────────────────────────────────────────


def test_recovery_migration_against_old_schema(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from stoic_eln.services.schema_migrations import (
        RECOVERY_COLUMNS,
        ensure_recovery_columns,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE inventory_item ("
                " id INTEGER PRIMARY KEY, batch_code VARCHAR(64),"
                " quantity_mL FLOAT, is_active BOOLEAN NOT NULL DEFAULT 1)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE mixture ("
                " id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL,"
                " kind VARCHAR(32) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO inventory_item (id, batch_code, quantity_mL) "
                "VALUES (1, 'OLD-1', 500.0)"
            )
        )
        conn.execute(
            text("INSERT INTO mixture (id, name, kind) VALUES (1, 'Eluente 9:1', 'eluent')")
        )

    actions = ensure_recovery_columns(engine)
    assert all("added" in a for a in actions)

    insp = inspect(engine)
    for table, cols in RECOVERY_COLUMNS.items():
        present = {c["name"] for c in insp.get_columns(table)}
        assert set(cols) <= present

    # Existing rows survive, and the NOT NULL flags are backfilled by
    # the DEFAULT rather than left dangling.
    with engine.connect() as conn:
        lot = conn.execute(
            text(
                "SELECT quantity_mL, is_recovered, recovery_use_count "
                "FROM inventory_item WHERE id = 1"
            )
        ).first()
        mix = conn.execute(
            text("SELECT name, is_recovered, recovery_signature FROM mixture WHERE id = 1")
        ).first()
    assert lot[0] == pytest.approx(500.0)
    assert lot[1] == 0 and lot[2] == 0
    assert mix[0] == "Eluente 9:1"
    assert mix[1] == 0 and mix[2] is None


def test_recovery_migration_is_idempotent(app):
    from stoic_eln.services.schema_migrations import ensure_recovery_columns

    with app.app_context():
        first = ensure_recovery_columns(db.engine)
        second = ensure_recovery_columns(db.engine)
    assert all("already present" in a for a in first)
    assert all("already present" in a for a in second)


# ── through the web layer ────────────────────────────────────────────


@pytest.fixture()
def logged_client(app, client, lab):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(lab["user"])
        sess["_fresh"] = True
    return client


def test_route_records_recovery(app, logged_client, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0)

    r = logged_client.post(
        f"/runs/{lab['run']}/step/{lab['step']}/recover",
        data={
            "component_ids": [str(lab["c_etoac"]), str(lab["c_hexane"])],
            "recovered_volume": "750",
            "location": "Scaffale B",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200

    with app.app_context():
        lot = db.session.query(InventoryItem).filter(InventoryItem.is_recovered.is_(True)).one()
        assert lot.quantity_mL == pytest.approx(750.0)
        assert lot.location == "Scaffale B"
        assert lot.mixture_id is not None


def test_route_refuses_recovery_on_a_draft(app, client, lab):
    """A draft has consumed nothing, so there is nothing in the flask."""
    with app.app_context():
        run = db.session.get(Run, lab["run"])
        run.status = "draft"
        db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(lab["user"])
        sess["_fresh"] = True

    client.post(
        f"/runs/{lab['run']}/step/{lab['step']}/recover",
        data={"component_ids": [str(lab["c_etoac"])], "recovered_volume": "100"},
        follow_redirects=True,
    )

    with app.app_context():
        assert (
            db.session.query(InventoryItem).filter(InventoryItem.is_recovered.is_(True)).count()
            == 0
        )


def test_recovery_form_appears_only_in_progress(app, logged_client, lab):
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0)

    html = logged_client.get(f"/runs/{lab['run']}").get_data(as_text=True)
    assert "Solvente recuperato" in html
    assert "Registra recupero" in html

    with app.app_context():
        run = db.session.get(Run, lab["run"])
        run.status = "draft"
        db.session.commit()

    html = logged_client.get(f"/runs/{lab['run']}").get_data(as_text=True)
    assert "Registra recupero" not in html


# ── v1.5.1: composition is declared, not computed ────────────────────


def test_single_component_needs_no_quantities_at_all(app, lab):
    """The case that was broken: nothing recorded, one solvent, works."""
    with app.app_context():
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"]], 250.0, user_id=lab["user"])
        db.session.commit()

        assert res.mixture is None
        assert res.lot.substance_id is not None
        assert res.shares[0].percent == pytest.approx(100.0)


def test_declared_percentages_beat_the_charged_ratio(app, lab):
    """Loaded 20:80, recovered 40:60 — the operator's reading wins.

    Recovery is not proportional: hexane (69 °C) comes over ahead of
    ethyl acetate (77 °C), so what is in the flask is not what went on
    the column.
    """
    with app.app_context():
        _set_volumes(lab, etoac=200.0, hexane=800.0)
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(
            step,
            [lab["c_etoac"], lab["c_hexane"]],
            700.0,
            percentages={lab["c_etoac"]: 40.0, lab["c_hexane"]: 60.0},
            user_id=lab["user"],
        )
        db.session.commit()

        by_sub = {c.substance_id: c.concentration for c in res.mixture.components}
        etoac_sub = db.session.get(RunStepComponent, lab["c_etoac"]).substance_id
        assert by_sub[etoac_sub] == pytest.approx(40.0)


def test_percentages_are_normalised_before_rounding(app, lab):
    """30/30/30 sums to 90 and must not be rejected."""
    with app.app_context():
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(
            step,
            [lab["c_etoac"], lab["c_hexane"], lab["c_water"]],
            900.0,
            percentages={lab["c_etoac"]: 30.0, lab["c_hexane"]: 30.0, lab["c_water"]: 30.0},
            user_id=lab["user"],
        )
        db.session.commit()
        assert sum(s.percent for s in res.shares) == pytest.approx(100.0)


def test_falls_back_to_charged_ratio_when_nothing_declared(app, lab):
    with app.app_context():
        _set_volumes(lab, etoac=300.0, hexane=700.0)
        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 500.0, user_id=lab["user"])
        db.session.commit()
        assert sorted(s.percent for s in res.shares) == [30.0, 70.0]


def test_multi_component_without_quantities_or_percentages_is_refused(app, lab):
    """Refused, but with a message that says what to do about it."""
    with app.app_context():
        step = db.session.get(RunStep, lab["step"])
        with pytest.raises(RecoveryError) as e:
            register_recovery(step, [lab["c_etoac"], lab["c_hexane"]], 500.0, user_id=lab["user"])
        assert "composizione" in str(e.value).lower()


def test_partial_percentages_are_refused(app, lab):
    with app.app_context():
        step = db.session.get(RunStep, lab["step"])
        with pytest.raises(RecoveryError):
            register_recovery(
                step,
                [lab["c_etoac"], lab["c_hexane"]],
                500.0,
                percentages={lab["c_etoac"]: 40.0},
                user_id=lab["user"],
            )


def test_negative_percentage_is_refused(app, lab):
    with app.app_context():
        step = db.session.get(RunStep, lab["step"])
        with pytest.raises(RecoveryError):
            register_recovery(
                step,
                [lab["c_etoac"], lab["c_hexane"]],
                500.0,
                percentages={lab["c_etoac"]: -10.0, lab["c_hexane"]: 110.0},
                user_id=lab["user"],
            )


def test_suggestion_is_none_without_quantities(app, lab):
    from stoic_eln.services.solvent_recovery import suggested_percentages

    with app.app_context():
        step = db.session.get(RunStep, lab["step"])
        comps = recoverable_components(step)
        assert suggested_percentages(comps) is None

        _set_volumes(lab, etoac=250.0, hexane=750.0)
        step = db.session.get(RunStep, lab["step"])
        pair = [
            sc for sc in recoverable_components(step) if sc.id in (lab["c_etoac"], lab["c_hexane"])
        ]
        sugg = suggested_percentages(pair)
        assert sugg[lab["c_etoac"]] == pytest.approx(25.0)


def test_section_renders_with_no_quantities_recorded(app, lab):
    """The user-visible half of the bug."""
    with app.app_context():
        user_id = lab["user"]

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True
        html = c.get(f"/runs/{lab['run']}").get_data(as_text=True)

    assert "Solvente recuperato" in html
    assert "Registra recupero" in html
    assert 'name="percent_' in html


# ── v1.5.2: a lot-less component is not an error ─────────────────────


def test_recovery_works_without_any_lot_bound(app, lab):
    """Regression: v1.5.1 refused this outright.

    A step component need not be bound to a lot — you can perfectly
    well recover solvent whose bottle was never registered. The Default
    group is assigned by InventoryItem's before_insert hook, which
    exists precisely for this.
    """
    with app.app_context():
        for cid in (lab["c_etoac"], lab["c_hexane"], lab["c_water"]):
            db.session.get(RunStepComponent, cid).inventory_item_id = None
        db.session.commit()

        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(step, [lab["c_etoac"]], 300.0, user_id=lab["user"])
        db.session.commit()

        assert res.lot.quantity_mL == pytest.approx(300.0)
        assert res.lot.group_id is not None  # filled in by the hook
        assert res.use_count == 1


def test_partially_bound_selection_still_inherits_a_group(app, lab):
    """One component with a lot, one without: the lot wins."""
    with app.app_context():
        db.session.get(RunStepComponent, lab["c_hexane"]).inventory_item_id = None
        source = db.session.get(InventoryItem, lab["l_etoac"])
        expected = source.group_id
        db.session.commit()

        step = db.session.get(RunStep, lab["step"])
        res = register_recovery(
            step,
            [lab["c_etoac"], lab["c_hexane"]],
            500.0,
            percentages={lab["c_etoac"]: 50.0, lab["c_hexane"]: 50.0},
            user_id=lab["user"],
        )
        db.session.commit()
        assert res.lot.group_id == expected
