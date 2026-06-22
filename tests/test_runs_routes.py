"""Integration tests for the runs blueprint."""

from __future__ import annotations

import re

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_component import ReactionComponent
from stoic_eln.models.run import STATUS_DRAFT, STATUS_IN_PROGRESS, Run
from stoic_eln.models.substance import Substance
from stoic_eln.models.user import User


def _login(client, username, password="x"):
    r = client.get("/auth/login")
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', r.data)
    csrf = m.group(1).decode() if m else ""
    return client.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "username": username,
            "password": password,
            "submit": "x",
        },
    )


def _csrf(client) -> str:
    r = client.get("/")
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', r.data)
    return m.group(1).decode() if m else ""


@pytest.fixture
def setup_data(app):
    """One published template + lots ready for an immediate run."""
    with app.app_context():
        u = User(
            username="ric",
            full_name="Riccardo",
            operator_code="RIC",
            role="user",
            is_admin=False,
            is_active=True,
            locale="it",
        )
        u.set_password("x")
        db.session.add(u)
        db.session.flush()

        sm = Substance(name="SM", smiles="CCO", molecular_formula="C2H6O", molecular_weight=46.07)
        cat = Substance(name="Cat", smiles="O", molecular_formula="H2O", molecular_weight=18.02)
        prod = Substance(
            name="Prod", smiles="CC=O", molecular_formula="C2H4O", molecular_weight=44.05
        )
        db.session.add_all([sm, cat, prod])
        db.session.flush()

        sm_lot = InventoryItem(
            substance_id=sm.id,
            batch_code="SM-A",
            quantity_g=100.0,
            initial_quantity_g=100.0,
            is_active=True,
        )
        cat_lot = InventoryItem(
            substance_id=cat.id,
            batch_code="CAT-A",
            quantity_g=100.0,
            initial_quantity_g=100.0,
            is_active=True,
        )
        db.session.add_all([sm_lot, cat_lot])
        db.session.flush()

        rxn = Reaction(
            code="RX-1", template_code="OXID", status="published", title="Test oxidation"
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
                    substance_id=cat.id,
                    role="catalyst",
                    position=1,
                    equivalents=1.0,
                ),
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=prod.id, role="product", position=2
                ),
            ]
        )
        db.session.commit()

        return {
            "user_id": u.id,
            "reaction_id": rxn.id,
            "sm_lot_id": sm_lot.id,
            "cat_lot_id": cat_lot.id,
            "sm_id": sm.id,
            "cat_id": cat.id,
            "prod_id": prod.id,
        }


# ─── Tests ───────────────────────────────────────────────────────────


def test_create_run_from_template_redirects_to_setup(app, client, setup_data):
    _login(client, "ric")
    csrf = _csrf(client)
    r = client.post(
        f"/runs/from/{setup_data['reaction_id']}",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "/runs/" in r.headers["Location"]


def test_run_setup_page_shows_components(app, client, setup_data):
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id

    r = client.get(f"/runs/{rid}")
    assert r.status_code == 200
    html = r.data.decode()
    assert "in preparazione" in html.lower() or "Run in preparazione" in html
    assert "Scala" in html
    assert "scegli lotto" in html.lower() or "scegli" in html.lower()


def test_full_lifecycle_via_routes(app, client, setup_data):
    """End-to-end: create draft → set scale → set lots+actuals →
    start → complete."""
    _login(client, "ric")
    csrf = _csrf(client)

    # 1. Create draft
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        comp_ids = {c.role: c.id for c in run.components}

    # 2. Set scale
    r = client.post(f"/runs/{rid}/scale", data={"csrf_token": csrf, "scale_mmol": "10"})
    assert r.status_code == 302

    # 3. Bind SM lot + actual
    client.post(
        f"/runs/{rid}/component/{comp_ids['starting_material']}/lot",
        data={"csrf_token": csrf, "lot_id": setup_data["sm_lot_id"]},
    )
    client.post(
        f"/runs/{rid}/component/{comp_ids['starting_material']}/actual",
        data={"csrf_token": csrf, "actual": "0.46"},
    )  # ~10 mmol × 46.07/1000

    # 4. Bind catalyst lot + actual
    client.post(
        f"/runs/{rid}/component/{comp_ids['catalyst']}/lot",
        data={"csrf_token": csrf, "lot_id": setup_data["cat_lot_id"]},
    )
    client.post(
        f"/runs/{rid}/component/{comp_ids['catalyst']}/actual",
        data={"csrf_token": csrf, "actual": "0.18"},
    )

    # 5. Start the run
    r = client.post(f"/runs/{rid}/start", data={"csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        run = db.session.get(Run, rid)
        assert run.status == STATUS_IN_PROGRESS
        # Inventory was deducted
        sm_lot = db.session.get(InventoryItem, setup_data["sm_lot_id"])
        assert abs(sm_lot.quantity_g - (100.0 - 0.46)) < 0.001

    # 6. Set product weight (this is the new way to record yield)
    with app.app_context():
        run = db.session.get(Run, rid)
        prod_cid = next(c.id for c in run.components if c.role == "product")
    client.post(
        f"/runs/{rid}/component/{prod_cid}/actual",
        data={"csrf_token": csrf, "actual": "0.3", "unit": "g"},
    )

    # 7. Complete the run
    r = client.post(f"/runs/{rid}/complete", data={"csrf_token": csrf})
    assert r.status_code == 302
    with app.app_context():
        run = db.session.get(Run, rid)
        assert run.is_completed
        assert run.yield_g == 0.3
        # 10 mmol × 44.05/1000 = 0.4405 → 0.3 / 0.4405 = 68.1%
        assert abs(run.yield_percent - 68.1) < 0.5
        # Verify auto-created lot
        from stoic_eln.models.inventory import InventoryItem as Inv

        lots = db.session.query(Inv).filter(Inv.source_run_id == rid).all()
        assert len(lots) == 1
        assert "P1" in lots[0].batch_code
        assert abs(lots[0].quantity_g - 0.3) < 0.001


def test_start_run_blocked_without_lot(app, client, setup_data):
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id

    client.post(f"/runs/{rid}/scale", data={"csrf_token": csrf, "scale_mmol": "10"})

    # Try to start without choosing any lot
    r = client.post(f"/runs/{rid}/start", data={"csrf_token": csrf}, follow_redirects=True)
    assert r.status_code == 200
    html = r.data.decode()
    assert "lotto" in html.lower()  # error flash present

    with app.app_context():
        run = db.session.get(Run, rid)
        assert run.status == STATUS_DRAFT  # didn't transition


def test_run_list_shows_runs(app, client, setup_data):
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})

    r = client.get("/runs/")
    assert r.status_code == 200
    assert b"OXID" in r.data  # template code shown


def test_cannot_create_run_from_draft_template(app, client, setup_data):
    _login(client, "ric")
    csrf = _csrf(client)
    with app.app_context():
        rxn = db.session.get(Reaction, setup_data["reaction_id"])
        rxn.status = "draft"
        db.session.commit()
    r = client.post(
        f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf}, follow_redirects=True
    )
    assert r.status_code == 200
    assert b"pubblicati" in r.data or b"published" in r.data


# ─── Patch 3 regression tests ────────────────────────────────────────


def test_scale_input_value_unit_remembered(app, client, setup_data):
    """When operator enters '500 mg' the value+unit are remembered."""
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id

    # Enter scale as 500 mg
    client.post(
        f"/runs/{rid}/scale", data={"csrf_token": csrf, "scale_amount": "500", "scale_unit": "mg"}
    )

    with app.app_context():
        run = db.session.get(Run, rid)
        assert run.scale_input_value == 500.0
        assert run.scale_input_unit == "mg"
        # MW = 46.07, so 500 mg = 500/46.07 = 10.85 mmol
        assert abs(run.scale_mmol - 10.85) < 0.05


def test_toggle_checklist_returns_partial_for_htmx(app, client, setup_data):
    """HTMX toggle returns just the <li>, not a full redirect."""
    from stoic_eln.models.run_step import RunChecklistItem

    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        # Add a checklist item directly
        item = RunChecklistItem(run_id=rid, text="Test item", position=0, is_done=False)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    # Toggle via HTMX header
    r = client.post(
        f"/runs/{rid}/checklist/{item_id}/toggle",
        data={"csrf_token": csrf},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    html = r.data.decode()
    # Returns the <li> partial, not a full page
    assert "<li" in html
    assert "<html" not in html
    assert f"run-chk-item-{item_id}" in html

    with app.app_context():
        item = db.session.get(RunChecklistItem, item_id)
        assert item.is_done is True


def test_toggle_checklist_redirects_when_not_htmx(app, client, setup_data):
    """Without HTMX header, falls back to full redirect (legacy behavior)."""
    from stoic_eln.models.run_step import RunChecklistItem

    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        item = RunChecklistItem(run_id=rid, text="x", position=0)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    r = client.post(f"/runs/{rid}/checklist/{item_id}/toggle", data={"csrf_token": csrf})
    assert r.status_code == 302


# ─── Patch 4 regression tests ────────────────────────────────────────


def test_set_actual_returns_204_for_htmx(app, client, setup_data):
    """HTMX auto-save: server returns 204 No Content, no redirect."""
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        cid = next(c.id for c in run.components if c.role == "starting_material")

    r = client.post(
        f"/runs/{rid}/component/{cid}/actual",
        data={"csrf_token": csrf, "actual": "0.5", "unit": "g"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 204
    assert r.data == b""


def test_set_lot_returns_204_for_htmx(app, client, setup_data):
    """HTMX auto-save for the lot picker: 204 No Content."""
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        cid = next(c.id for c in run.components if c.role == "starting_material")

    r = client.post(
        f"/runs/{rid}/component/{cid}/lot",
        data={"csrf_token": csrf, "lot_id": setup_data["sm_lot_id"]},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 204


def test_set_actual_still_redirects_without_htmx(app, client, setup_data):
    """Fallback: without HX-Request header, full redirect (legacy)."""
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        cid = next(c.id for c in run.components if c.role == "starting_material")

    r = client.post(
        f"/runs/{rid}/component/{cid}/actual",
        data={"csrf_token": csrf, "actual": "0.5", "unit": "g"},
    )
    assert r.status_code == 302


# ── P2c: aggiungi step a run avviato ─────────────────────────────


def test_add_step_to_draft_run(app, client, setup_data):
    """A new step can be added to a draft run."""
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        step_count_before = len(run.steps)

    r = client.post(
        f"/runs/{rid}/step/add",
        data={"csrf_token": csrf, "title": "Estrazione con EtOAc", "kind": "extraction"},
        follow_redirects=False,
    )
    assert r.status_code == 302

    with app.app_context():
        run = db.session.get(Run, rid)
        assert len(run.steps) == step_count_before + 1
        new_step = run.steps[-1]
        assert new_step.title == "Estrazione con EtOAc"
        assert new_step.kind == "extraction"
        assert new_step.template_step_id is None


def test_add_step_to_in_progress_run(app, client, setup_data):
    """A new step can be added to an in-progress run."""
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        run.status = STATUS_IN_PROGRESS
        db.session.commit()

    r = client.post(
        f"/runs/{rid}/step/add",
        data={"csrf_token": csrf, "title": "Colonna flash", "kind": "purification"},
        follow_redirects=False,
    )
    assert r.status_code == 302

    with app.app_context():
        run = db.session.get(Run, rid)
        titles = [s.title for s in run.steps]
        assert "Colonna flash" in titles


def test_add_step_requires_title(app, client, setup_data):
    """A step without a title is rejected with a redirect (flash warning)."""
    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        step_count_before = len(run.steps)

    r = client.post(
        f"/runs/{rid}/step/add",
        data={"csrf_token": csrf, "title": "", "kind": "other"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    with app.app_context():
        run = db.session.get(Run, rid)
        assert len(run.steps) == step_count_before


def test_add_step_blocked_on_completed_run(app, client, setup_data):
    """Completed runs are immutable: adding a step is rejected."""
    from stoic_eln.models.run import STATUS_COMPLETED

    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})
    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id
        run.status = STATUS_COMPLETED
        db.session.commit()
        step_count_before = len(run.steps)

    r = client.post(
        f"/runs/{rid}/step/add",
        data={"csrf_token": csrf, "title": "Nuovo step", "kind": "other"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    with app.app_context():
        run = db.session.get(Run, rid)
        assert len(run.steps) == step_count_before


def test_add_step_from_library(app, client, setup_data):
    """Cloning a StepTemplate creates a RunStep with the template's name
    and copies its components."""
    from stoic_eln.models.step_template import StepTemplate, StepTemplateComponent
    from stoic_eln.models.substance import Substance

    _login(client, "ric")
    csrf = _csrf(client)
    client.post(f"/runs/from/{setup_data['reaction_id']}", data={"csrf_token": csrf})

    with app.app_context():
        run = db.session.query(Run).first()
        rid = run.id

        # Create a minimal StepTemplate in the library
        sub = db.session.query(Substance).first()
        tmpl = StepTemplate(name="Estrazione standard", kind="extraction")
        db.session.add(tmpl)
        db.session.flush()
        db.session.add(
            StepTemplateComponent(
                template_id=tmpl.id,
                substance_id=sub.id,
                role="solvent",
                ratio_kind="mL_per_g",
                ratio_value=10.0,
                position=0,
            )
        )
        db.session.commit()
        tmpl_id = tmpl.id
        step_count_before = len(run.steps)

    r = client.post(
        f"/runs/{rid}/step/add",
        data={"csrf_token": csrf, "template_step_id": str(tmpl_id)},
        follow_redirects=False,
    )
    assert r.status_code == 302

    with app.app_context():
        run = db.session.get(Run, rid)
        assert len(run.steps) == step_count_before + 1
        new_step = run.steps[-1]
        assert new_step.title == "Estrazione standard"
        assert new_step.kind == "extraction"
        assert new_step.template_step_id is None
        assert len(new_step.components) == 1
        assert new_step.components[0].ratio_value == 10.0
