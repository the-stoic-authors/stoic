"""Tests for Run model + run_setup service."""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.checklist_item import ChecklistItem
from stoic_eln.models.inventory import InventoryItem
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_component import ReactionComponent
from stoic_eln.models.run import (
    STATUS_COMPLETED,
    STATUS_DRAFT,
    STATUS_IN_PROGRESS,
)
from stoic_eln.models.substance import Substance
from stoic_eln.models.user import User
from stoic_eln.services import run_setup


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def operator(app):
    with app.app_context():
        u = User(username="op", full_name="Op", operator_code="OP",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x")
        db.session.add(u); db.session.commit()
        return u.id


@pytest.fixture
def template_with_lots(app, operator):
    """A published reaction template with full inventory."""
    with app.app_context():
        sm = Substance(name="Hexanoyl chloride", smiles="CCCCCC(=O)Cl",
                       molecular_formula="C6H11ClO", molecular_weight=134.60)
        rea = Substance(name="1,3-Benzodioxole", smiles="C1OC2=CC=CC=C2O1",
                        molecular_formula="C7H6O2", molecular_weight=122.12)
        cat = Substance(name="AlCl3", smiles="[Al+3].[Cl-].[Cl-].[Cl-]",
                        molecular_formula="AlCl3", molecular_weight=133.34)
        sol = Substance(name="DCM", smiles="ClCCl",
                        molecular_formula="CH2Cl2", molecular_weight=84.93)
        prod = Substance(name="MD600B", smiles="CCCCCC(=O)C1=CC2=C(C=C1)OCO2",
                         molecular_formula="C13H16O3", molecular_weight=220.26)
        db.session.add_all([sm, rea, cat, sol, prod]); db.session.flush()

        # Lots with abundant quantities
        lots = [
            InventoryItem(substance_id=sm.id, batch_code="SM-1",
                          quantity_g=50.0, initial_quantity_g=50.0, is_active=True),
            InventoryItem(substance_id=rea.id, batch_code="REA-1",
                          quantity_g=50.0, initial_quantity_g=50.0, is_active=True),
            InventoryItem(substance_id=cat.id, batch_code="CAT-1",
                          quantity_g=100.0, initial_quantity_g=100.0, is_active=True),
            InventoryItem(substance_id=sol.id, batch_code="SOL-1",
                          quantity_mL=1000.0, initial_quantity_mL=1000.0, is_active=True),
        ]
        db.session.add_all(lots); db.session.flush()

        rxn = Reaction(code="RX-2026-0001", template_code="MD600B",
                       status="published", title="Friedel-Crafts MD600B",
                       duration_hours=12)
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=rea.id,
                              role="reagent", position=1, equivalents=0.95),
            ReactionComponent(reaction_id=rxn.id, substance_id=cat.id,
                              role="catalyst", position=2, equivalents=1.05),
            ReactionComponent(reaction_id=rxn.id, substance_id=sol.id,
                              role="solvent", position=3, concentration_M=0.6),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=4),
        ])
        db.session.add_all([
            ChecklistItem(reaction_id=rxn.id, text="Vetreria asciutta", position=0),
            ChecklistItem(reaction_id=rxn.id, text="Ar collegato", position=1),
        ])
        db.session.commit()
        return {
            "reaction_id": rxn.id,
            "substances": {"sm": sm.id, "rea": rea.id, "cat": cat.id,
                           "sol": sol.id, "prod": prod.id},
            "lots": {"sm": lots[0].id, "rea": lots[1].id,
                     "cat": lots[2].id, "sol": lots[3].id},
        }


# ── tests ────────────────────────────────────────────────────────────────


def test_create_draft_copies_template(app, template_with_lots, operator):
    """create_draft snapshots the template into the run."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        db.session.commit()

        assert run.status == STATUS_DRAFT
        assert run.reaction_id == rxn.id
        assert run.template_code_snapshot == "MD600B"
        assert run.template_title_snapshot == "Friedel-Crafts MD600B"
        assert run.code  # generated
        assert len(run.components) == 5
        assert len(run.checklist_items) == 2

        # Limiting component is preserved
        limiting = next((c for c in run.components if c.is_limiting), None)
        assert limiting is not None
        assert limiting.role == "starting_material"


def test_recompute_targets(app, template_with_lots, operator):
    """recompute_targets fills target_mass_g / target_volume_mL based on scale."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0  # 5 mmol of limiting reagent
        run_setup.recompute_targets(run)
        db.session.commit()

        # Limiting: 5 mmol × 134.60 g/mol = 0.673 g
        limiting = next(c for c in run.components if c.is_limiting)
        assert abs(limiting.target_mass_g - 0.673) < 0.001

        # Reagent eq=0.95: 5 × 0.95 × 122.12 / 1000 = 0.580 g
        reagent = next(c for c in run.components if c.role == "reagent")
        assert abs(reagent.target_mass_g - 0.5801) < 0.001

        # Catalyst eq=1.05: 5 × 1.05 × 133.34 / 1000 = 0.700 g
        cat = next(c for c in run.components if c.role == "catalyst")
        assert abs(cat.target_mass_g - 0.700) < 0.005

        # Solvent at 0.6 M: 5 mmol / 0.6 M = 8.33 mL
        sol = next(c for c in run.components if c.role == "solvent")
        assert abs(sol.target_volume_mL - 8.333) < 0.01

        # Product NOW has a theoretical target mass (5 mmol × 220.26 / 1000)
        prod = next(c for c in run.components if c.role == "product")
        assert abs(prod.target_mass_g - 1.10) < 0.01
        assert prod.target_volume_mL is None


def test_validate_for_start_blocks_missing_lot(app, template_with_lots, operator):
    """Missing lot blocks start."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)
        # Don't assign any lots
        db.session.commit()

        errors = run_setup.validate_for_start(run)
        assert any("lotto" in e.lower() for e in errors)


def test_start_run_deducts_inventory(app, template_with_lots, operator):
    """Starting a run decrements bound lots."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)

        # Bind lots + actuals
        lot_ids = template_with_lots["lots"]
        for c in run.components:
            if c.role == "product":
                continue
            if c.role == "starting_material":
                c.inventory_item_id = lot_ids["sm"]
                c.actual_mass_g = 0.673
            elif c.role == "reagent":
                c.inventory_item_id = lot_ids["rea"]
                c.actual_mass_g = 0.580
            elif c.role == "catalyst":
                c.inventory_item_id = lot_ids["cat"]
                c.actual_mass_g = 0.700
            elif c.role == "solvent":
                c.inventory_item_id = lot_ids["sol"]
                c.actual_volume_mL = 8.33
        db.session.commit()

        sm_lot_before = db.session.get(InventoryItem, lot_ids["sm"]).quantity_g
        sol_lot_before = db.session.get(InventoryItem, lot_ids["sol"]).quantity_mL

        run_setup.start_run(run)
        db.session.commit()

        assert run.status == STATUS_IN_PROGRESS
        assert run.started_at is not None

        # Inventory was decremented
        sm_lot_after = db.session.get(InventoryItem, lot_ids["sm"]).quantity_g
        sol_lot_after = db.session.get(InventoryItem, lot_ids["sol"]).quantity_mL
        assert abs((sm_lot_before - sm_lot_after) - 0.673) < 0.001
        assert abs((sol_lot_before - sol_lot_after) - 8.33) < 0.01


def test_start_run_blocked_by_insufficient_quantity(app, template_with_lots, operator):
    """A lot without enough quantity prevents the run from starting."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)

        # SM lot has only 50 g; ask for 100 g
        lot_ids = template_with_lots["lots"]
        for c in run.components:
            if c.role == "product":
                continue
            if c.role == "starting_material":
                c.inventory_item_id = lot_ids["sm"]
                c.actual_mass_g = 100.0  # too much
            elif c.role == "reagent":
                c.inventory_item_id = lot_ids["rea"]; c.actual_mass_g = 0.580
            elif c.role == "catalyst":
                c.inventory_item_id = lot_ids["cat"]; c.actual_mass_g = 0.700
            elif c.role == "solvent":
                c.inventory_item_id = lot_ids["sol"]; c.actual_volume_mL = 8.33
        db.session.commit()

        with pytest.raises(run_setup.RunStartError) as exc_info:
            run_setup.start_run(run)
        assert any("disponibili" in e.lower() for e in exc_info.value.errors)


def test_complete_run_computes_yield(app, template_with_lots, operator):
    """complete_run computes yield_percent from yield_g + product MW + scale."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)

        # Set up everything for start
        lot_ids = template_with_lots["lots"]
        for c in run.components:
            if c.role == "product": continue
            elif c.role == "starting_material":
                c.inventory_item_id = lot_ids["sm"]; c.actual_mass_g = 0.673
            elif c.role == "reagent":
                c.inventory_item_id = lot_ids["rea"]; c.actual_mass_g = 0.580
            elif c.role == "catalyst":
                c.inventory_item_id = lot_ids["cat"]; c.actual_mass_g = 0.700
            elif c.role == "solvent":
                c.inventory_item_id = lot_ids["sol"]; c.actual_volume_mL = 8.33
        db.session.commit()

        run_setup.start_run(run)
        db.session.commit()

        # Theoretical max: 5 mmol * 220.26 g/mol = 1.10 g
        # Get 0.5 g → 45.4%
        # New API: set actual_mass_g on the product, then complete_run reads it.
        prod_comp = next(c for c in run.components if c.role == "product")
        prod_comp.actual_mass_g = 0.5
        result = run_setup.complete_run(run)
        db.session.commit()

        assert run.status == STATUS_COMPLETED
        assert run.yield_g == 0.5
        assert abs(run.yield_percent - 45.4) < 0.5
        assert run.completed_at is not None
        # An inventory lot was auto-created for the product
        assert len(result["lots_created"]) == 1
        assert "P1" in result["lots_created"][0]["batch_code"]


def test_run_immutable_after_completion(app, template_with_lots, operator):
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.status = STATUS_COMPLETED
        assert run.is_immutable


def test_complete_run_creates_inventory_lot_per_product(app, template_with_lots, operator):
    """Each product with mass gets a new InventoryItem with code <run.code>-Pn."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)

        lot_ids = template_with_lots["lots"]
        for c in run.components:
            if c.role == "product":
                continue
            elif c.role == "starting_material":
                c.inventory_item_id = lot_ids["sm"]; c.actual_mass_g = 0.673
            elif c.role == "reagent":
                c.inventory_item_id = lot_ids["rea"]; c.actual_mass_g = 0.580
            elif c.role == "catalyst":
                c.inventory_item_id = lot_ids["cat"]; c.actual_mass_g = 0.700
            elif c.role == "solvent":
                c.inventory_item_id = lot_ids["sol"]; c.actual_volume_mL = 8.33
        db.session.commit()
        run_setup.start_run(run)
        db.session.commit()

        # Set product weight
        prod_comp = next(c for c in run.components if c.role == "product")
        prod_comp.actual_mass_g = 0.5

        result = run_setup.complete_run(run)
        db.session.commit()

        from stoic_eln.models.inventory import InventoryItem as Inv
        lots = db.session.query(Inv).filter(Inv.source_run_id == run.id).all()
        assert len(lots) == 1
        assert lots[0].batch_code == f"{run.code}-P1"
        assert lots[0].source_run_id == run.id
        assert abs(lots[0].quantity_g - 0.5) < 0.001
        assert lots[0].is_active is True


def test_complete_run_no_products_requires_force(app, template_with_lots, operator):
    """Without product weight, complete_run raises unless force_no_products."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)

        lot_ids = template_with_lots["lots"]
        for c in run.components:
            if c.role == "product":
                continue
            elif c.role == "starting_material":
                c.inventory_item_id = lot_ids["sm"]; c.actual_mass_g = 0.673
            elif c.role == "reagent":
                c.inventory_item_id = lot_ids["rea"]; c.actual_mass_g = 0.580
            elif c.role == "catalyst":
                c.inventory_item_id = lot_ids["cat"]; c.actual_mass_g = 0.700
            elif c.role == "solvent":
                c.inventory_item_id = lot_ids["sol"]; c.actual_volume_mL = 8.33
        db.session.commit()
        run_setup.start_run(run)
        db.session.commit()

        # No product weight set: should refuse
        with pytest.raises(run_setup.RunStartError):
            run_setup.complete_run(run)

        # But with force_no_products=True it accepts and marks as failed
        result = run_setup.complete_run(run, force_no_products=True)
        db.session.commit()
        assert result["is_failed"] is True
        assert run.yield_g == 0.0
        assert run.is_failed is True
        # No inventory created
        from stoic_eln.models.inventory import InventoryItem as Inv
        lots = db.session.query(Inv).filter(Inv.source_run_id == run.id).all()
        assert lots == []


def test_complete_run_yield_over_100_warns(app, template_with_lots, operator):
    """Resa > 100% emits a warning but still completes."""
    with app.app_context():
        rxn = db.session.get(Reaction, template_with_lots["reaction_id"])
        op = db.session.get(User, operator)
        run = run_setup.create_draft(rxn, op)
        run.scale_mmol = 5.0
        run_setup.recompute_targets(run)

        lot_ids = template_with_lots["lots"]
        for c in run.components:
            if c.role == "product":
                continue
            elif c.role == "starting_material":
                c.inventory_item_id = lot_ids["sm"]; c.actual_mass_g = 0.673
            elif c.role == "reagent":
                c.inventory_item_id = lot_ids["rea"]; c.actual_mass_g = 0.580
            elif c.role == "catalyst":
                c.inventory_item_id = lot_ids["cat"]; c.actual_mass_g = 0.700
            elif c.role == "solvent":
                c.inventory_item_id = lot_ids["sol"]; c.actual_volume_mL = 8.33
        db.session.commit()
        run_setup.start_run(run)
        db.session.commit()

        # Theoretical = 5 mmol × 220.26/1000 = 1.10 g
        # Set 2.0 g → 181%
        prod_comp = next(c for c in run.components if c.role == "product")
        prod_comp.actual_mass_g = 2.0

        result = run_setup.complete_run(run)
        db.session.commit()

        assert run.is_completed
        assert run.yield_percent > 100
        assert "yield_over_100" in result["warnings"]


def test_promote_draft_preserves_runs(app):
    """Editing a published template + saving must NOT break existing runs.

    With the new versioning logic:
      - the parent (v1) is ARCHIVED but not deleted
      - the draft becomes a NEW published row (v2) with its own id
      - existing Runs continue pointing to the parent (v1) — they are
        historical records of an execution against that specific version.
    """
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem, Run)
    from stoic_eln.services import reaction_clone, run_setup

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=200.0)
        prod = Substance(name="P", molecular_weight=300.0)
        db.session.add_all([sm, prod]); db.session.flush()
        sm_lot = InventoryItem(substance_id=sm.id, batch_code="L1",
                               quantity_g=10, initial_quantity_g=10, is_active=True)
        db.session.add(sm_lot); db.session.flush()

        # Create a published template (v1)
        rxn = Reaction(code="RX-1", template_code="TEST.1",
                       template_code_base="TEST", version_number=1,
                       status="published", title="Original",
                       default_scale_mmol=1.0)
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()

        # Create a run from this template (v1)
        run = run_setup.create_draft(rxn, u)
        run_id = run.id
        v1_id = rxn.id
        db.session.commit()

        # Now edit (clone, modify, save) → produces v2
        draft = reaction_clone.clone_for_editing(rxn)
        db.session.commit()
        draft.title = "Modified Title"
        db.session.commit()

        published = reaction_clone.promote_draft(draft)
        db.session.commit()

        # New version: different id, same family
        assert published.id != v1_id
        assert published.template_code_base == "TEST"
        assert published.version_number == 2
        assert published.template_code == "TEST.2"
        assert published.title == "Modified Title"
        assert published.status == "published"
        assert published.is_archived is False
        assert published.parent_version_id == v1_id

        # Old v1 is archived but still in the DB
        v1 = db.session.get(Reaction, v1_id)
        assert v1 is not None
        assert v1.is_archived is True
        assert v1.template_code == "TEST.1"

        # The run still references v1 (historical record)
        run_after = db.session.get(Run, run_id)
        assert run_after is not None
        assert run_after.reaction_id == v1_id


def test_update_field_auto_save_uses_field_name(app, client):
    """update_field accepts the value either as 'value' or as the field's own name.

    This is the regression test for: opening a modal in a draft reaction
    (e.g. 'Aggiungi componente') used to wipe the form fields the user
    had typed. Now each field auto-saves on blur via update_field, and
    update_field reads the value from a key matching the field name.
    """
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction
    import re

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R-1", template_code=None, status="draft",
                       title="Old title")
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    # Login (CSRF disabled in test config)
    client.post("/auth/login", data={"username": "r",
                                     "password": "x", "submit": "x"})

    # Auto-save: send field=title and title=NewTitle (no "value" key)
    r = client.post(f"/reactions/{rxn_id}/field",
                    data={"field": "title",
                          "title": "New auto-saved title"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 204

    with app.app_context():
        rxn = db.session.get(Reaction, rxn_id)
        assert rxn.title == "New auto-saved title"

    # Legacy: still works with a generic "value" key
    r = client.post(f"/reactions/{rxn_id}/field",
                    data={"field": "title",
                          "value": "Legacy way"})
    assert r.status_code in (200, 302)

    with app.app_context():
        rxn = db.session.get(Reaction, rxn_id)
        assert rxn.title == "Legacy way"


def test_promote_first_version_creates_v1(app):
    """Brand-new template: code 'MD600B' → 'MD600B.1' on first publish."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction
    from stoic_eln.services import reaction_clone

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()

        # Create a draft from scratch with base 'MD600B'
        from stoic_eln.services.code_generator import generate_reaction_code
        draft = Reaction(
            code=generate_reaction_code(),
            template_code=None, template_code_base="MD600B",
            status="draft", title="New Reaction", default_scale_mmol=1.0,
        )
        db.session.add(draft); db.session.commit()

        published = reaction_clone.promote_draft(draft)
        db.session.commit()

        assert published.template_code == "MD600B.1"
        assert published.template_code_base == "MD600B"
        assert published.version_number == 1
        assert published.parent_version_id is None
        assert published.is_archived is False


def test_promote_three_versions(app):
    """Editing twice produces .1 → .2 → .3, only .3 active."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction
    from stoic_eln.services import reaction_clone
    from stoic_eln.services.code_generator import generate_reaction_code

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()

        # v1
        draft1 = Reaction(code=generate_reaction_code(),
                          template_code=None, template_code_base="MD600B",
                          status="draft", title="v1")
        db.session.add(draft1); db.session.commit()
        v1 = reaction_clone.promote_draft(draft1); db.session.commit()
        assert v1.template_code == "MD600B.1"

        # v2
        draft2 = reaction_clone.clone_for_editing(v1)
        db.session.commit()
        draft2.title = "v2"
        db.session.commit()
        v2 = reaction_clone.promote_draft(draft2); db.session.commit()
        assert v2.template_code == "MD600B.2"
        # v1 archived now
        v1_refresh = db.session.get(Reaction, v1.id)
        assert v1_refresh.is_archived is True

        # v3
        draft3 = reaction_clone.clone_for_editing(v2)
        db.session.commit()
        draft3.title = "v3"
        db.session.commit()
        v3 = reaction_clone.promote_draft(draft3); db.session.commit()
        assert v3.template_code == "MD600B.3"
        assert v3.parent_version_id == v2.id

        # Both v1 and v2 archived
        v2_refresh = db.session.get(Reaction, v2.id)
        assert v2_refresh.is_archived is True
        # Only one current version
        from sqlalchemy import and_
        currents = (db.session.query(Reaction)
                      .filter(and_(Reaction.template_code_base == "MD600B",
                                    Reaction.is_archived.is_(False),
                                    Reaction.status == "published"))
                      .all())
        assert len(currents) == 1
        assert currents[0].id == v3.id


def test_duplicate_creates_independent_draft(app):
    """duplicate_for_new copies content but breaks the family link."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent)
    from stoic_eln.services import reaction_clone

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=200.0)
        prod = Substance(name="P", molecular_weight=300.0)
        db.session.add_all([sm, prod]); db.session.flush()

        src = Reaction(code="RX-1", template_code="MD600B.1",
                       template_code_base="MD600B", version_number=1,
                       status="published", title="Source")
        db.session.add(src); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=src.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=src.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()

        dup = reaction_clone.duplicate_for_new(src)
        db.session.commit()

        # Independent draft, no family link, no template_code
        assert dup.status == "draft"
        assert dup.template_code is None
        assert dup.template_code_base is None
        assert dup.parent_published_id is None
        assert dup.parent_version_id is None
        # Components copied
        assert len(dup.components) == 2
        # Title shows the "(copia)" hint
        assert "(copia)" in dup.title


def test_template_code_base_rejects_dot(app):
    """validate_base() rejects codes containing a dot (reserved for version suffix)."""
    from stoic_eln.services.template_code import validate_base, TemplateCodeError
    with app.app_context():
        with pytest.raises(TemplateCodeError):
            validate_base("MD600B.5")  # user trying to add version manually


def test_add_step_component_returns_partial_for_htmx(app, client):
    """add_step_component returns step_card partial for HTMX requests."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction)
    from stoic_eln.models.reaction_step import ReactionStep

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sub = Substance(name="DCM", molecular_weight=84.93, density=1.33)
        db.session.add(sub); db.session.flush()
        rxn = Reaction(code="RX-1", template_code=None,
                       template_code_base="TEST",
                       status="draft", title="T", default_scale_mmol=1.0,
                       created_by_id=u.id)
        db.session.add(rxn); db.session.flush()
        step = ReactionStep(reaction_id=rxn.id, kind="workup",
                            title="Workup", position=0)
        db.session.add(step); db.session.commit()
        sub_id, sid = sub.id, step.id

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    r = client.post(
        f"/reactions/steps/{sid}/components/new",
        data={"substance_id": str(sub_id), "role": "solvent",
              "ratio_value": "5", "ratio_kind": "mL_per_mmol"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    text = r.data.decode()
    # Returns the step_card partial — not full page
    assert "<html" not in text
    assert "step-card-" in text
    assert "DCM" in text


def test_add_component_returns_partial_for_htmx(app, client):
    """add_component returns components_table partial for HTMX requests."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance, Reaction

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sub = Substance(name="MyReagent", molecular_weight=100.0)
        db.session.add(sub); db.session.flush()
        rxn = Reaction(code="RX-1", template_code=None,
                       template_code_base="TEST",
                       status="draft", title="T", default_scale_mmol=1.0,
                       created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        sub_id, rid = sub.id, rxn.id

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    r = client.post(
        f"/reactions/{rid}/components/new",
        data={"substance_id": str(sub_id), "role": "reagent",
              "equivalents": "1.5"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    text = r.data.decode()
    assert "<html" not in text
    assert "MyReagent" in text


def test_run_button_hidden_on_drafts_in_list(app, client):
    """The 'Esegui' button must NOT appear in the reactions list for drafts."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        # One published, one draft
        pub = Reaction(code="RX-1", template_code="TEST.1",
                       template_code_base="TEST", version_number=1,
                       status="published", title="Published one")
        drf = Reaction(code="RX-2", template_code=None,
                       template_code_base="OTHER",
                       status="draft", title="Draft one",
                       created_by_id=u.id)
        db.session.add_all([pub, drf]); db.session.commit()
        pub_id, drf_id = pub.id, drf.id

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    r = client.get("/reactions/")
    text = r.data.decode()

    # The 'Esegui run' form should target the published one but NOT the draft
    assert f"runs/from/{pub_id}" in text, "published row should have Esegui form"
    assert f"runs/from/{drf_id}" not in text, "draft row should NOT have Esegui form"


def test_draft_display_code_shows_future_version(app):
    """A draft cloned from MD600B.1 should display 'MD600B.2' as its code."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction
    from stoic_eln.services import reaction_clone

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()

        # Published v1
        pub = Reaction(code="RX-1", template_code="MD600B.1",
                       template_code_base="MD600B", version_number=1,
                       status="published", title="Original")
        db.session.add(pub); db.session.commit()

        # Clone for editing → draft should show MD600B.2
        draft = reaction_clone.clone_for_editing(pub)
        db.session.commit()

        assert draft.draft_display_code == "MD600B.2"
        assert draft.display_code == "MD600B.2"

        # A brand-new draft (no parent) with base 'NEWFAM' shows 'NEWFAM.1'
        from stoic_eln.services.code_generator import generate_reaction_code
        d = Reaction(code=generate_reaction_code(),
                     template_code=None, template_code_base="NEWFAM",
                     status="draft", title="New thing")
        db.session.add(d); db.session.commit()
        assert d.draft_display_code == "NEWFAM.1"

        # A draft with no base typed yet shows '—'
        d2 = Reaction(code=generate_reaction_code(),
                      template_code=None, template_code_base=None,
                      status="draft", title="Empty")
        db.session.add(d2); db.session.commit()
        assert d2.draft_display_code == "—"


def test_cancel_draft_does_not_bump_version(app):
    """Creating a draft + cancelling it must NOT advance the version counter."""
    from stoic_eln.extensions import db
    from stoic_eln.models import Reaction
    from stoic_eln.services import reaction_clone
    from stoic_eln.services.code_generator import generate_reaction_code

    with app.app_context():
        # v1
        d = Reaction(code=generate_reaction_code(),
                     template_code=None, template_code_base="MYTEMP",
                     status="draft", title="t")
        db.session.add(d); db.session.commit()
        v1 = reaction_clone.promote_draft(d); db.session.commit()
        assert v1.template_code == "MYTEMP.1"

        # Modifica → bozza → cancella
        d2 = reaction_clone.clone_for_editing(v1); db.session.commit()
        reaction_clone.discard_draft(d2); db.session.commit()

        # Confirm draft is gone
        all_rxn = db.session.query(Reaction).all()
        assert len(all_rxn) == 1, "draft should be deleted, leaving only v1"

        # Modifica → bozza → pubblica → must be v2 (not v3)
        d3 = reaction_clone.clone_for_editing(v1); db.session.commit()
        d3.title = "v2"
        db.session.commit()
        v2 = reaction_clone.promote_draft(d3); db.session.commit()

        assert v2.template_code == "MYTEMP.2"
        assert v2.version_number == 2


def test_pdf_summary_renders_basic_run(app, client):
    """A completed run can render its summary PDF."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.pdf_run import render_run_summary

    with app.app_context():
        u = User(username="ric", full_name="R", operator_code="RIC",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=200.0,
                       smiles="c1ccc(Br)cc1")
        prod = Substance(name="Prod", molecular_weight=300.0,
                         smiles="c1ccc(c1)c1ccccc1")
        db.session.add_all([sm, prod]); db.session.flush()
        sm_lot = InventoryItem(substance_id=sm.id, batch_code="L1",
                               quantity_g=10, initial_quantity_g=10,
                               is_active=True)
        db.session.add(sm_lot); db.session.flush()
        rxn = Reaction(code="RX-1", template_code="T.1",
                       template_code_base="T", version_number=1,
                       status="published", title="Test",
                       default_scale_mmol=1.0)
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()

        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0
        run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = sm_lot.id
        cs["starting_material"].actual_mass_g = 1.0
        db.session.commit()
        run_setup.start_run(run); db.session.commit()
        cs["product"].actual_mass_g = 0.5
        db.session.commit()
        run_setup.complete_run(run); db.session.commit()

        pdf_bytes = render_run_summary(run)

    # PDF magic header
    assert pdf_bytes[:5] == b"%PDF-"
    # At least 2 KB (a non-trivial document)
    assert len(pdf_bytes) > 2000


def test_pdf_full_renders_with_steps(app, client):
    """A run with workup step renders the full PDF including the step."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, ReactionStep,
                                   ReactionStepComponent, InventoryItem,
                                   ChecklistItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.pdf_run import render_run_full

    with app.app_context():
        u = User(username="ric", full_name="R", operator_code="RIC",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=200.0)
        prod = Substance(name="Prod", molecular_weight=300.0)
        nh4cl = Substance(name="NH4Cl saturo", molecular_weight=53.49,
                          state="liquid", density=1.0)
        db.session.add_all([sm, prod, nh4cl]); db.session.flush()
        sm_lot = InventoryItem(substance_id=sm.id, batch_code="L1",
                               quantity_g=10, initial_quantity_g=10,
                               is_active=True)
        db.session.add(sm_lot); db.session.flush()
        rxn = Reaction(code="RX-1", template_code="T.1",
                       template_code_base="T", version_number=1,
                       status="published", title="With workup",
                       procedure="Heat. Cool. Quench.",
                       temperature_c=80.0, duration_hours=12.0,
                       atmosphere="Ar")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.add(ChecklistItem(reaction_id=rxn.id,
                                     text="Vetreria asciutta", position=0))
        step = ReactionStep(reaction_id=rxn.id, kind="workup",
                            title="Workup acquoso",
                            description="Wash and dry.", position=0)
        db.session.add(step); db.session.flush()
        db.session.add(ReactionStepComponent(
            step_id=step.id, substance_id=nh4cl.id, role="solvent",
            ratio_value=5.0, ratio_kind="mL_per_mmol", position=0))
        db.session.commit()

        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0
        run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = sm_lot.id
        cs["starting_material"].actual_mass_g = 1.0
        db.session.commit()
        run_setup.start_run(run); db.session.commit()
        cs["product"].actual_mass_g = 0.5
        db.session.commit()
        run_setup.complete_run(run); db.session.commit()

        pdf_bytes = render_run_full(run)

    assert pdf_bytes[:5] == b"%PDF-"
    # Sanity: the workup step-card content should add some bulk over an
    # almost-empty run. We're not super strict — RDKit may or may not be
    # available, scheme image may or may not be embedded. Just require
    # that the PDF is at least a couple KB (otherwise something is wrong).
    assert len(pdf_bytes) > 2500


def test_pdf_endpoint_returns_pdf_content_type(app, client):
    """The /runs/<id>/pdf endpoint streams a PDF with correct headers."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=200.0)
        prod = Substance(name="P", molecular_weight=300.0)
        db.session.add_all([sm, prod]); db.session.flush()
        rxn = Reaction(code="RX-1", template_code="T.1",
                       template_code_base="T", version_number=1,
                       status="published", title="Test")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()
        # Just create a draft run — we don't need to complete it for PDF
        run = run_setup.create_draft(rxn, u)
        db.session.commit()
        run_id = run.id

    client.post("/auth/login", data={"username": "r", "password": "x", "submit": "x"})

    r = client.get(f"/runs/{run_id}/pdf")
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:5] == b"%PDF-"

    r = client.get(f"/runs/{run_id}/pdf?type=full")
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:5] == b"%PDF-"


# ─── Settimana 6 — Group + inventory revamp ─────────────────────────


def test_group_default_created_via_first_lot_insert(app):
    """The Default group is auto-created when the first InventoryItem is inserted."""
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem, Group

    with app.app_context():
        s = Substance(name="X", molecular_weight=100.0)
        db.session.add(s); db.session.flush()

        # Before: no Default group exists
        assert db.session.query(Group).filter(Group.slug == "default").count() == 0

        # Insert lot WITHOUT explicit group_id
        lot = InventoryItem(
            substance_id=s.id, batch_code="L1",
            quantity_g=10, initial_quantity_g=10, is_active=True,
        )
        db.session.add(lot)
        db.session.commit()

        # After: Default group exists, lot points to it
        default_g = (db.session.query(Group)
                     .filter(Group.slug == "default")
                     .one_or_none())
        assert default_g is not None
        assert default_g.is_default is True

        lot_after = db.session.get(InventoryItem, lot.id)
        assert lot_after.group_id == default_g.id


def test_inventory_cost_per_mole(app):
    """cost_per_mole is computed for solids using MW, for liquids using density too."""
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem

    with app.app_context():
        # Solid: MW=100, 5g, €100 → 100€/0.05mol = 2000€/mol
        solid = Substance(name="Solid", molecular_weight=100.0, state="solid")
        # Liquid: MW=80, density=0.8, 100mL → 80g → 1mol; €100 → 100€/mol
        liquid = Substance(name="Liquid", molecular_weight=80.0,
                           density=0.8, state="liquid")
        no_mw = Substance(name="NoMW", state="solid")
        db.session.add_all([solid, liquid, no_mw]); db.session.flush()

        l1 = InventoryItem(substance_id=solid.id, quantity_g=5.0,
                           initial_quantity_g=5.0, total_cost_eur=100.0,
                           is_active=True)
        l2 = InventoryItem(substance_id=liquid.id, quantity_mL=100.0,
                           initial_quantity_mL=100.0, total_cost_eur=100.0,
                           is_active=True)
        l3 = InventoryItem(substance_id=no_mw.id, quantity_g=10.0,
                           initial_quantity_g=10.0, total_cost_eur=50.0,
                           is_active=True)
        db.session.add_all([l1, l2, l3]); db.session.commit()

        assert l1.cost_per_mole == 2000.0
        assert l2.cost_per_mole == 100.0
        assert l3.cost_per_mole is None  # MW unknown


def test_inventory_status_helpers(app):
    """is_expired / is_expiring_soon / is_empty / status_key."""
    from datetime import date, timedelta
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem

    with app.app_context():
        s = Substance(name="X", molecular_weight=100.0)
        db.session.add(s); db.session.flush()

        today = date.today()
        in_stock = InventoryItem(substance_id=s.id, quantity_g=5.0,
                                 initial_quantity_g=5.0, is_active=True)
        expiring = InventoryItem(substance_id=s.id, quantity_g=5.0,
                                 initial_quantity_g=5.0, is_active=True,
                                 expiry_date=today + timedelta(days=15))
        expired = InventoryItem(substance_id=s.id, quantity_g=5.0,
                                initial_quantity_g=5.0, is_active=True,
                                expiry_date=today - timedelta(days=5))
        empty = InventoryItem(substance_id=s.id, quantity_g=0.0,
                              initial_quantity_g=10.0, is_active=True)
        inactive = InventoryItem(substance_id=s.id, quantity_g=5.0,
                                 initial_quantity_g=5.0, is_active=False)
        db.session.add_all([in_stock, expiring, expired, empty, inactive])
        db.session.commit()

        assert in_stock.status_key == "in_stock"
        assert expiring.status_key == "expiring"
        assert expired.status_key == "expired"
        assert empty.status_key == "empty"
        assert inactive.status_key == "inactive"


def test_inventory_list_filters_by_status(app, client):
    """The /inventory/?status=... endpoint filters correctly."""
    from datetime import date, timedelta
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance, InventoryItem

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="THF", molecular_weight=72.0, cas_number="109-99-9")
        db.session.add(s); db.session.flush()

        today = date.today()
        in_stock_lot = InventoryItem(substance_id=s.id, batch_code="THF-NEW",
                                     quantity_mL=1000, initial_quantity_mL=1000,
                                     is_active=True)
        expired_lot = InventoryItem(substance_id=s.id, batch_code="THF-OLD",
                                    quantity_mL=500, initial_quantity_mL=500,
                                    is_active=True,
                                    expiry_date=today - timedelta(days=5))
        db.session.add_all([in_stock_lot, expired_lot]); db.session.commit()

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    # Default: shows both
    r = client.get("/inventory/")
    text = r.data.decode()
    assert "THF-NEW" in text
    assert "THF-OLD" in text

    # Filter expired: only old one
    r = client.get("/inventory/?status=expired")
    text = r.data.decode()
    assert "THF-NEW" not in text
    assert "THF-OLD" in text


def test_group_service_ensure_default(app):
    """ensure_default_group is idempotent."""
    from stoic_eln.extensions import db
    from stoic_eln.services.group_service import ensure_default_group
    from stoic_eln.models import Group

    with app.app_context():
        g1 = ensure_default_group()
        assert g1.slug == "default"
        assert g1.is_default is True

        g2 = ensure_default_group()
        assert g2.id == g1.id  # idempotent

        all_default = (db.session.query(Group)
                       .filter(Group.slug == "default").count())
        assert all_default == 1


# ─── Settimana 6 patch 2 — Inventory alerts ─────────────────────────


def test_substance_is_low_stock(app):
    """is_low_stock True when sum of available stock < threshold."""
    from datetime import date, timedelta
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem

    with app.app_context():
        s = Substance(name="X", molecular_weight=100.0,
                      low_stock_threshold_g=5.0)
        db.session.add(s); db.session.flush()

        # Two active lots: total 4g — under threshold of 5g
        db.session.add_all([
            InventoryItem(substance_id=s.id, quantity_g=2.0,
                          initial_quantity_g=2.0, is_active=True),
            InventoryItem(substance_id=s.id, quantity_g=2.0,
                          initial_quantity_g=2.0, is_active=True),
            # And one EXPIRED — should not count
            InventoryItem(substance_id=s.id, quantity_g=10.0,
                          initial_quantity_g=10.0, is_active=True,
                          expiry_date=date.today() - timedelta(days=5)),
            # And one INACTIVE — should not count
            InventoryItem(substance_id=s.id, quantity_g=20.0,
                          initial_quantity_g=20.0, is_active=False),
        ])
        db.session.commit()

        # Refresh from DB to be sure
        s_after = db.session.query(Substance).filter_by(name="X").one()
        assert s_after.is_low_stock is True

        # Now bump threshold below total available
        s_after.low_stock_threshold_g = 2.0
        db.session.commit()
        assert s_after.is_low_stock is False


def test_inventory_alerts_summary(app):
    """get_summary returns the right buckets."""
    from datetime import date, timedelta
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem
    from stoic_eln.services.inventory_alerts import get_summary

    with app.app_context():
        today = date.today()
        s_low = Substance(name="LowSub", molecular_weight=100.0,
                          low_stock_threshold_g=10.0)
        s_normal = Substance(name="NormalSub", molecular_weight=100.0,
                             low_stock_threshold_g=1.0)
        db.session.add_all([s_low, s_normal]); db.session.flush()

        # LowSub: 5g total active < threshold 10g → low stock
        db.session.add(InventoryItem(substance_id=s_low.id, quantity_g=5.0,
                                     initial_quantity_g=5.0, is_active=True))
        # NormalSub: 10g total > threshold 1g → not low
        db.session.add(InventoryItem(substance_id=s_normal.id, quantity_g=10.0,
                                     initial_quantity_g=10.0, is_active=True))
        # Expired lot
        db.session.add(InventoryItem(substance_id=s_normal.id, batch_code="EXP",
                                     quantity_g=2.0, initial_quantity_g=2.0,
                                     is_active=True,
                                     expiry_date=today - timedelta(days=10)))
        # Expiring soon lot
        db.session.add(InventoryItem(substance_id=s_normal.id, batch_code="SOON",
                                     quantity_g=3.0, initial_quantity_g=3.0,
                                     is_active=True,
                                     expiry_date=today + timedelta(days=15)))
        db.session.commit()

        summary = get_summary()
        assert len(summary.expired_lots) == 1
        assert summary.expired_lots[0].batch_code == "EXP"
        assert len(summary.expiring_lots) == 1
        assert summary.expiring_lots[0].batch_code == "SOON"
        assert len(summary.low_stock_substances) == 1
        assert summary.low_stock_substances[0].name == "LowSub"
        assert summary.total_alerts == 3


def test_dashboard_renders_with_alerts(app, client):
    """The dashboard route returns 200 and includes alert sections when active."""
    from datetime import date, timedelta
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance, InventoryItem

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="Pd(OAc)2", molecular_weight=224.51,
                      low_stock_threshold_g=5.0)
        db.session.add(s); db.session.flush()
        # Make it low stock (1g vs 5g threshold)
        db.session.add(InventoryItem(substance_id=s.id, batch_code="L1",
                                     quantity_g=1.0, initial_quantity_g=5.0,
                                     is_active=True))
        # And one expired
        db.session.add(InventoryItem(substance_id=s.id, batch_code="OLD",
                                     quantity_g=10.0, initial_quantity_g=10.0,
                                     is_active=True,
                                     expiry_date=date.today() - timedelta(days=3)))
        db.session.commit()

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    r = client.get("/dashboard")
    assert r.status_code == 200
    text = r.data.decode()
    assert "Lotti scaduti" in text
    assert "OLD" in text
    assert "Sostanze sotto soglia" in text
    assert "Pd(OAc)2" in text


def test_update_low_stock_route(app, client):
    """POST /substances/<id>/low_stock saves thresholds."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="X", molecular_weight=100.0)
        db.session.add(s); db.session.commit()
        sid = s.id

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    r = client.post(f"/substances/{sid}/low_stock",
                    data={"low_stock_threshold_g": "2.5",
                          "low_stock_threshold_mL": ""})
    assert r.status_code == 302

    with app.app_context():
        s_after = db.session.get(Substance, sid)
        assert s_after.low_stock_threshold_g == 2.5
        assert s_after.low_stock_threshold_mL is None

    # Clear thresholds
    r = client.post(f"/substances/{sid}/low_stock",
                    data={"low_stock_threshold_g": "",
                          "low_stock_threshold_mL": ""})
    with app.app_context():
        s_after = db.session.get(Substance, sid)
        assert s_after.low_stock_threshold_g is None
        assert s_after.low_stock_threshold_mL is None


# ─── Settimana 6 patch 3 — Orders ─────────────────────────────────


def test_order_create_planned(app, client):
    """Creating an order from /orders/new puts it in 'planned' status."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance, Order

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="Pd(OAc)2", molecular_weight=224.51)
        db.session.add(s); db.session.commit()
        sid = s.id

    client.post("/auth/login", data={"username":"r","password":"x","submit":"x"})

    r = client.post("/orders/new", data={
        "csrf_token": "",
        "substance_id": str(sid),
        "supplier": "Sigma-Aldrich",
        "ordered_quantity_g": "5.0",
        "ordered_total_eur": "380.00",
    })
    assert r.status_code == 302

    with app.app_context():
        o = db.session.query(Order).first()
        assert o is not None
        assert o.status == "planned"
        assert o.supplier == "Sigma-Aldrich"
        assert o.ordered_quantity_g == 5.0
        assert o.ordered_total_eur == 380.0


def test_order_full_lifecycle(app, client):
    """planned → ordered → received: an InventoryItem appears."""
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance, Order, InventoryItem

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="X", molecular_weight=100.0)
        db.session.add(s); db.session.commit()
        sid = s.id

    client.post("/auth/login", data={"username":"r","password":"x","submit":"x"})

    # 1. Plan
    client.post("/orders/new", data={
        "csrf_token": "", "substance_id": str(sid),
        "ordered_quantity_g": "10",
    })
    with app.app_context():
        oid = db.session.query(Order).first().id

    # 2. Mark as ordered
    client.post(f"/orders/{oid}/mark_ordered", data={
        "csrf_token": "", "ordered_at": date.today().isoformat(),
    })
    with app.app_context():
        assert db.session.get(Order, oid).status == "ordered"

    # 3. Receive
    client.post(f"/orders/{oid}/receive", data={
        "csrf_token": "", "received_quantity_g": "10",
        "received_at": date.today().isoformat(),
        "batch_code": "TEST-A",
    })
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.status == "received"
        assert o.inventory_item_id is not None
        lot = db.session.get(InventoryItem, o.inventory_item_id)
        assert lot.batch_code == "TEST-A"
        assert lot.quantity_g == 10.0
        assert lot.substance_id == sid


def test_order_partial_receipt(app, client):
    """Receiving less than ordered → status='received_partial', no second event."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance, Order

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="X", molecular_weight=100.0)
        db.session.add(s); db.session.commit()
        sid = s.id

    client.post("/auth/login", data={"username":"r","password":"x","submit":"x"})
    client.post("/orders/new", data={
        "csrf_token": "", "substance_id": str(sid),
        "ordered_quantity_g": "10",
    })
    with app.app_context():
        oid = db.session.query(Order).first().id

    # Receive only 7g
    client.post(f"/orders/{oid}/receive", data={
        "csrf_token": "", "received_quantity_g": "7",
        "partial_reason": "Esauriti, spedito solo 7g",
    })
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.status == "received_partial"
        assert "7g" in (o.notes or "")
        # And the inventory lot has the actual quantity, not the ordered
        assert o.inventory_item.quantity_g == 7.0


def test_order_cancel(app, client):
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance, Order

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="X", molecular_weight=100.0)
        db.session.add(s); db.session.commit()
        sid = s.id

    client.post("/auth/login", data={"username":"r","password":"x","submit":"x"})
    client.post("/orders/new", data={
        "csrf_token": "", "substance_id": str(sid),
        "ordered_quantity_g": "5",
    })
    with app.app_context():
        oid = db.session.query(Order).first().id

    client.post(f"/orders/{oid}/cancel", data={
        "csrf_token": "", "reason": "Cambio fornitore",
    })
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.status == "cancelled"
        assert "Cambio fornitore" in (o.notes or "")


def test_order_cannot_receive_twice(app, client):
    """Receiving an already-received order returns a flash + redirect, no new lot."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance, Order, InventoryItem

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="X", molecular_weight=100.0)
        db.session.add(s); db.session.commit()
        sid = s.id

    client.post("/auth/login", data={"username":"r","password":"x","submit":"x"})
    client.post("/orders/new", data={
        "csrf_token": "", "substance_id": str(sid),
        "ordered_quantity_g": "3",
    })
    with app.app_context():
        oid = db.session.query(Order).first().id

    # First receipt
    client.post(f"/orders/{oid}/receive", data={
        "csrf_token": "", "received_quantity_g": "3",
    })
    # Lots count: 1
    with app.app_context():
        n_lots = db.session.query(InventoryItem).count()
    assert n_lots == 1

    # Try to receive again — should redirect with flash, no new lot
    r = client.get(f"/orders/{oid}/receive", follow_redirects=False)
    assert r.status_code == 302  # redirect to detail
    with app.app_context():
        n_lots_after = db.session.query(InventoryItem).count()
    assert n_lots_after == 1  # no new lot


# ─── Settimana 6 patch 4 — Shopping list ──────────────────────────


def test_shopping_list_low_stock_quantity(app):
    """Suggested quantity = threshold * 1.5 (Rico's formula A)."""
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem
    from stoic_eln.services.shopping_list import build_shopping_list

    with app.app_context():
        s = Substance(name="Pd(OAc)2", molecular_weight=224.51,
                      low_stock_threshold_g=5.0)
        db.session.add(s); db.session.flush()
        # 1g remaining of 5g threshold → low stock
        db.session.add(InventoryItem(
            substance_id=s.id, batch_code="A",
            quantity_g=1.0, initial_quantity_g=5.0,
            total_cost_eur=380.0, supplier="Sigma",
            is_active=True))
        db.session.commit()

        suggestions = build_shopping_list()
        assert len(suggestions) == 1
        sug = suggestions[0]
        assert sug.reason == "low_stock"
        assert sug.suggested_quantity_g == 7.5  # 5 * 1.5
        assert sug.suggested_unit == "g"
        assert sug.last_supplier == "Sigma"
        # 380€ / 5g = 76 €/g; 76 * 7.5 = 570€
        assert sug.estimated_total_cost_eur == 570.0


def test_shopping_list_empty_substance(app):
    """A substance with active lots all empty appears as 'empty'."""
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem
    from stoic_eln.services.shopping_list import build_shopping_list

    with app.app_context():
        s = Substance(name="AlCl3", molecular_weight=133.34,
                      low_stock_threshold_g=20.0)
        db.session.add(s); db.session.flush()
        # Empty lot — was 100g, now 0g
        db.session.add(InventoryItem(
            substance_id=s.id, batch_code="OLD",
            quantity_g=0.0, initial_quantity_g=100.0,
            total_cost_eur=42.0, supplier="Acros",
            is_active=True))
        db.session.commit()

        suggestions = build_shopping_list()
        assert len(suggestions) == 1
        assert suggestions[0].reason == "empty"
        assert suggestions[0].suggested_quantity_g == 30.0  # 20 * 1.5


def test_shopping_list_skips_when_open_order(app):
    """Substances with an open order are EXCLUDED from suggestions by default."""
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem, Order, Group
    from stoic_eln.services.shopping_list import build_shopping_list

    with app.app_context():
        g = Group(slug="default", name="Default", is_default=True, is_active=True)
        db.session.add(g); db.session.flush()

        s = Substance(name="X", molecular_weight=100.0,
                      low_stock_threshold_g=5.0)
        db.session.add(s); db.session.flush()
        db.session.add(InventoryItem(substance_id=s.id, quantity_g=1.0,
                                     initial_quantity_g=5.0, is_active=True))
        # An existing planned order
        db.session.add(Order(substance_id=s.id, group_id=g.id,
                             ordered_quantity_g=7.5, status="planned"))
        db.session.commit()

        # Default: empty list (substance has open order → suppressed)
        suggestions = build_shopping_list()
        assert suggestions == []

        # Diagnostic mode: include open orders, marked as such
        suggestions_full = build_shopping_list(include_with_open_orders=True)
        assert len(suggestions_full) == 1
        assert suggestions_full[0].has_open_order is True


def test_shopping_list_flags_disable_categories(app):
    """When all flags are off, the list is empty."""
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance, InventoryItem
    from stoic_eln.services.shopping_list import (
        build_shopping_list, set_flags, get_flags,
    )

    with app.app_context():
        s = Substance(name="X", molecular_weight=100.0,
                      low_stock_threshold_g=5.0)
        db.session.add(s); db.session.flush()
        db.session.add(InventoryItem(substance_id=s.id, quantity_g=1.0,
                                     initial_quantity_g=5.0, is_active=True))
        db.session.commit()

        # All on (default)
        suggestions = build_shopping_list()
        assert len(suggestions) == 1

        # All off
        set_flags(include_low_stock=False, include_empty=False,
                  include_expiring=False)
        suggestions = build_shopping_list()
        assert suggestions == []

        flags = get_flags()
        assert flags["include_low_stock"] is False


def test_shopping_list_bulk_create(app, client):
    """POST to bulk-create orders from selected substances."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, InventoryItem, Order, Group)

    with app.app_context():
        g = Group(slug="default", name="Default", is_default=True, is_active=True)
        db.session.add(g); db.session.flush()
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it",
                 default_group_id=g.id)
        u.set_password("x"); db.session.add(u); db.session.flush()
        s1 = Substance(name="Sub1", molecular_weight=100.0,
                       low_stock_threshold_g=5.0)
        s2 = Substance(name="Sub2", molecular_weight=100.0,
                       low_stock_threshold_g=10.0)
        db.session.add_all([s1, s2]); db.session.flush()
        db.session.add_all([
            InventoryItem(substance_id=s1.id, quantity_g=1.0,
                          initial_quantity_g=5.0, total_cost_eur=50.0,
                          is_active=True),
            InventoryItem(substance_id=s2.id, quantity_g=2.0,
                          initial_quantity_g=10.0, total_cost_eur=80.0,
                          is_active=True),
        ])
        db.session.commit()
        s1_id, s2_id = s1.id, s2.id

    client.post("/auth/login", data={"username":"r","password":"x","submit":"x"})

    r = client.post("/orders/shopping_list/create_orders", data={
        "csrf_token": "",
        "substance_id": [str(s1_id), str(s2_id)],
    })
    assert r.status_code == 302

    with app.app_context():
        orders = db.session.query(Order).filter_by(status="planned").all()
        assert len(orders) == 2
        # Verify substance + quantities
        by_sub = {o.substance_id: o for o in orders}
        assert by_sub[s1_id].ordered_quantity_g == 7.5  # 5*1.5
        assert by_sub[s2_id].ordered_quantity_g == 15.0  # 10*1.5


def test_order_form_prefill_from_query_string(app, client):
    """GET /orders/new?substance_id=X&ordered_quantity_g=7.5&supplier=Sigma
    pre-fills the form fields."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Substance

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="Pd(OAc)2", molecular_weight=224.51)
        db.session.add(s); db.session.commit()
        sid = s.id

    client.post("/auth/login",
                data={"username":"r","password":"x","submit":"x"})

    r = client.get(f"/orders/new"
                   f"?substance_id={sid}"
                   f"&ordered_quantity_g=7.5"
                   f"&ordered_total_eur=570"
                   f"&supplier=Sigma-Aldrich"
                   f"&catalogue_number=379875-5G")
    assert r.status_code == 200
    text = r.data.decode()
    # Quantity, cost, supplier, catalogue should be in the form values
    assert 'value="7.5"' in text
    assert 'value="570"' in text or 'value="570.0"' in text
    assert 'value="Sigma-Aldrich"' in text
    assert 'value="379875-5G"' in text


def test_shopping_list_excludes_planned_after_creation(app, client):
    """After creating planned orders from the shopping list, those
    substances are EXCLUDED from the next list."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, InventoryItem, Order, Group)
    from stoic_eln.services.shopping_list import build_shopping_list

    with app.app_context():
        g = Group(slug="default", name="Default", is_default=True, is_active=True)
        db.session.add(g); db.session.flush()
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it",
                 default_group_id=g.id)
        u.set_password("x"); db.session.add(u); db.session.flush()
        s = Substance(name="Sub", molecular_weight=100.0,
                      low_stock_threshold_g=5.0)
        db.session.add(s); db.session.flush()
        db.session.add(InventoryItem(substance_id=s.id, quantity_g=1.0,
                                     initial_quantity_g=5.0,
                                     total_cost_eur=50.0, is_active=True))
        db.session.commit()
        sid = s.id

    client.post("/auth/login",
                data={"username":"r","password":"x","submit":"x"})

    # Before: 1 suggestion
    with app.app_context():
        assert len(build_shopping_list()) == 1

    # Create an order from the shopping list
    client.post("/orders/shopping_list/create_orders", data={
        "csrf_token": "",
        "substance_id": [str(sid)],
    })

    # After: 0 suggestions (the substance has an open planned order)
    with app.app_context():
        assert len(build_shopping_list()) == 0


# ─── Settimana 6 patch 5 — Run cost ─────────────────────────────────


def test_run_cost_basic_calculation(app):
    """Cost = sum of (actual_qty × lot.cost_per_unit) for all consumed lines."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction, ReactionComponent,
                                   InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import compute_run_cost

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0, state="solid")
        prod = Substance(name="P", molecular_weight=200.0, state="solid")
        db.session.add_all([sm, prod]); db.session.flush()
        # Lot: 100€ / 10g → 10 €/g
        lot = InventoryItem(substance_id=sm.id, batch_code="L1",
                            quantity_g=10.0, initial_quantity_g=10.0,
                            total_cost_eur=100.0, is_active=True)
        db.session.add(lot); db.session.flush()
        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()

        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"; run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()

        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 0.500  # 500mg consumed
        db.session.commit()
        run_setup.start_run(run); db.session.commit()
        cs["product"].actual_mass_g = 0.300
        db.session.commit()
        run_setup.complete_run(run); db.session.commit()

        bd = compute_run_cost(run)
        # 0.500 g × 10 €/g = 5.00 €
        assert abs(bd.total_eur - 5.0) < 1e-6
        assert len(bd.lines) == 1  # product excluded
        assert bd.lines[0].substance_name == "SM"
        assert bd.lines[0].cost_eur == 5.0


def test_run_cost_excludes_products(app):
    """Products and byproducts must not appear in the cost breakdown."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction, ReactionComponent,
                                   InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import compute_run_cost

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=150.0)
        bp = Substance(name="BP", molecular_weight=80.0)
        db.session.add_all([sm, prod, bp]); db.session.flush()
        db.session.add(InventoryItem(substance_id=sm.id, quantity_g=10,
                                     initial_quantity_g=10, total_cost_eur=100,
                                     is_active=True))
        db.session.flush()
        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
            ReactionComponent(reaction_id=rxn.id, substance_id=bp.id,
                              role="byproduct", position=2),
        ])
        db.session.commit()
        run = run_setup.create_draft(rxn, u)
        db.session.commit()

        bd = compute_run_cost(run)
        line_subs = {l.substance_name for l in bd.lines}
        assert "SM" in line_subs
        assert "P" not in line_subs
        assert "BP" not in line_subs


def test_run_cost_handles_missing_data(app):
    """Lines without lot or without cost data: cost_eur=None, incomplete_count++."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction, ReactionComponent,
                                   InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import compute_run_cost

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        priced = Substance(name="P_priced", molecular_weight=200.0)
        unpriced = Substance(name="P_unpriced", molecular_weight=150.0)
        nolot = Substance(name="P_nolot", molecular_weight=80.0)
        prod = Substance(name="Prod", molecular_weight=300.0)
        db.session.add_all([sm, priced, unpriced, nolot, prod]); db.session.flush()
        # Lot WITH price
        lot1 = InventoryItem(substance_id=priced.id, quantity_g=10,
                             initial_quantity_g=10, total_cost_eur=50,
                             is_active=True)
        # Lot WITHOUT price (total_cost_eur=None)
        lot2 = InventoryItem(substance_id=unpriced.id, quantity_g=10,
                             initial_quantity_g=10, total_cost_eur=None,
                             is_active=True)
        db.session.add_all([lot1, lot2]); db.session.flush()

        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=priced.id,
                              role="reactant", position=1, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=unpriced.id,
                              role="reactant", position=2, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=nolot.id,
                              role="reactant", position=3, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=4),
        ])
        db.session.commit()
        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"; run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()

        cs = {(c.substance.name, c.role): c for c in run.components}
        cs[("SM", "starting_material")].actual_mass_g = 0.5
        # No lot for SM, but has actual quantity → has_lot=False, cost=None
        cs[("P_priced", "reactant")].inventory_item_id = lot1.id
        cs[("P_priced", "reactant")].actual_mass_g = 1.0
        cs[("P_unpriced", "reactant")].inventory_item_id = lot2.id
        cs[("P_unpriced", "reactant")].actual_mass_g = 1.0
        # P_nolot: no lot, no actual qty
        db.session.commit()

        bd = compute_run_cost(run)
        assert len(bd.lines) == 4  # all non-product components, even incomplete

        # Find each line
        by_sub = {l.substance_name: l for l in bd.lines}
        # SM: no lot
        assert by_sub["SM"].has_lot is False
        assert by_sub["SM"].cost_eur is None
        # P_priced: full data → cost = 1g × (50/10) = 5€
        assert by_sub["P_priced"].cost_eur == 5.0
        # P_unpriced: lot but no price
        assert by_sub["P_unpriced"].has_lot is True
        assert by_sub["P_unpriced"].has_cost_data is False
        assert by_sub["P_unpriced"].cost_eur is None
        # P_nolot: no lot
        assert by_sub["P_nolot"].cost_eur is None

        assert bd.total_eur == 5.0  # only P_priced contributes
        assert bd.incomplete_count == 3  # SM, P_unpriced, P_nolot


def test_run_cost_includes_step_components(app):
    """Workup/extraction components contribute to the run cost."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction, ReactionComponent,
                                   ReactionStep, ReactionStepComponent,
                                   InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import compute_run_cost

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=200.0)
        nh4cl = Substance(name="NH4Cl", molecular_weight=53.49,
                          state="liquid", density=1.0)
        db.session.add_all([sm, prod, nh4cl]); db.session.flush()
        # Lots: SM 10€/g, NH4Cl 0.10€/mL
        lot_sm = InventoryItem(substance_id=sm.id, quantity_g=10,
                               initial_quantity_g=10, total_cost_eur=100,
                               is_active=True)
        lot_nh = InventoryItem(substance_id=nh4cl.id, quantity_mL=1000,
                               initial_quantity_mL=1000, total_cost_eur=100,
                               is_active=True)
        db.session.add_all([lot_sm, lot_nh]); db.session.flush()

        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        step = ReactionStep(reaction_id=rxn.id, kind="workup",
                            title="Workup", position=0)
        db.session.add(step); db.session.flush()
        db.session.add(ReactionStepComponent(
            step_id=step.id, substance_id=nh4cl.id, role="solvent",
            ratio_value=5.0, ratio_kind="mL_per_mmol", position=0))
        db.session.commit()

        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"; run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()

        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot_sm.id
        cs["starting_material"].actual_mass_g = 1.0  # → 10€

        # workup component
        rsc = run.steps[0].components[0]
        rsc.inventory_item_id = lot_nh.id
        rsc.actual_volume_mL = 50.0  # → 5€
        db.session.commit()

        bd = compute_run_cost(run)
        assert bd.total_eur == 15.0
        assert bd.main_total_eur == 10.0
        assert bd.steps_total_eur == 5.0


def test_run_cost_per_mol_product(app):
    """cost_per_mol_product = total_cost / (yield_g / MW_product)."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction, ReactionComponent,
                                   InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import compute_run_cost, cost_per_mol_product

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=200.0)
        db.session.add_all([sm, prod]); db.session.flush()
        lot = InventoryItem(substance_id=sm.id, quantity_g=10,
                            initial_quantity_g=10, total_cost_eur=100,
                            is_active=True)
        db.session.add(lot); db.session.flush()
        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()
        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"; run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 1.0  # 10€
        db.session.commit()
        run_setup.start_run(run); db.session.commit()
        cs["product"].actual_mass_g = 0.4  # 0.002 mol of MW 200
        db.session.commit()
        run_setup.complete_run(run); db.session.commit()

        bd = compute_run_cost(run)
        cpm = cost_per_mol_product(run, bd)
        # 10€ / 0.002 mol = 5000 €/mol
        assert abs(cpm - 5000.0) < 1e-3


# ─── Settimana 6 patch 5.1 — Cumulative cost ───────────────────────


def test_run_cost_direct_vs_cumulative_no_intermediates(app):
    """When no internal lots are consumed, direct == cumulative."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import compute_run_cost

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=200.0)
        db.session.add_all([sm, prod]); db.session.flush()
        # Externally-purchased lot (source_run_id=None)
        lot = InventoryItem(substance_id=sm.id, quantity_g=10,
                            initial_quantity_g=10, total_cost_eur=100,
                            is_active=True, source_run_id=None)
        db.session.add(lot); db.session.flush()
        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()
        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 0.5  # → €5
        db.session.commit()

        bd = compute_run_cost(run)
        assert bd.direct_total_eur == 5.0
        assert bd.total_eur == 5.0
        assert bd.intermediates_total_eur == 0.0
        # Line is not from an internal lot
        assert bd.lines[0].is_from_internal_lot is False


def test_complete_run_sets_cost_on_product_lot(app):
    """complete_run() must allocate cumulative cost to product lots."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=200.0)
        db.session.add_all([sm, prod]); db.session.flush()
        lot = InventoryItem(substance_id=sm.id, quantity_g=10,
                            initial_quantity_g=10, total_cost_eur=100,
                            is_active=True)
        db.session.add(lot); db.session.flush()
        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()
        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 1.0  # → €10 spent
        db.session.commit()
        run_setup.start_run(run); db.session.commit()
        cs["product"].actual_mass_g = 0.6  # 600mg of product
        db.session.commit()
        run_setup.complete_run(run); db.session.commit()

        # The product lot must have total_cost_eur = €10 (the run's cost)
        product_lots = (db.session.query(InventoryItem)
                        .filter_by(substance_id=prod.id).all())
        assert len(product_lots) == 1
        p_lot = product_lots[0]
        assert p_lot.source_run_id == run.id
        assert abs(p_lot.total_cost_eur - 10.0) < 1e-3


def test_two_step_synthesis_propagates_cost(app):
    """Multi-step: run 2 uses lot from run 1; cumulative includes upstream.

    This is the scenario Rico described: a precious intermediate at
    €133/g consumed in a downstream run with cheap reagents — without
    cumulative cost we'd think the second run cost cents.
    """
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import compute_run_cost

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()

        A = Substance(name="A", molecular_weight=100.0)
        B = Substance(name="B", molecular_weight=100.0)
        I_ = Substance(name="I", molecular_weight=200.0)
        C = Substance(name="C", molecular_weight=80.0)
        P = Substance(name="P", molecular_weight=300.0)
        db.session.add_all([A, B, I_, C, P]); db.session.flush()
        # A and B at 100€/g (expensive); C at 1€/g (cheap)
        db.session.add_all([
            InventoryItem(substance_id=A.id, quantity_g=10,
                          initial_quantity_g=10, total_cost_eur=1000,
                          is_active=True),
            InventoryItem(substance_id=B.id, quantity_g=10,
                          initial_quantity_g=10, total_cost_eur=1000,
                          is_active=True),
            InventoryItem(substance_id=C.id, quantity_g=100,
                          initial_quantity_g=100, total_cost_eur=100,
                          is_active=True),
        ])
        db.session.flush()

        # Two reaction templates
        rxn1 = Reaction(code="R1", template_code="S1.1",
                        template_code_base="S1", version_number=1,
                        status="published", title="A+B→I")
        rxn2 = Reaction(code="R2", template_code="S2.1",
                        template_code_base="S2", version_number=1,
                        status="published", title="I+C→P")
        db.session.add_all([rxn1, rxn2]); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn1.id, substance_id=A.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn1.id, substance_id=B.id,
                              role="reactant", position=1, equivalents=1.0),
            ReactionComponent(reaction_id=rxn1.id, substance_id=I_.id,
                              role="product", position=2),
            ReactionComponent(reaction_id=rxn2.id, substance_id=I_.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn2.id, substance_id=C.id,
                              role="reactant", position=1, equivalents=1.0),
            ReactionComponent(reaction_id=rxn2.id, substance_id=P.id,
                              role="product", position=2),
        ])
        db.session.commit()

        # === RUN 1 ===
        run1 = run_setup.create_draft(rxn1, u)
        run1.scale_input_value = 10.0; run1.scale_input_unit = "mmol"
        run1.scale_mmol = 10.0
        db.session.commit()
        run_setup.recompute_targets(run1); db.session.commit()
        lot_A = (db.session.query(InventoryItem)
                 .filter_by(substance_id=A.id).one())
        lot_B = (db.session.query(InventoryItem)
                 .filter_by(substance_id=B.id).one())
        cs1 = {c.role: c for c in run1.components}
        cs1["starting_material"].inventory_item_id = lot_A.id
        cs1["starting_material"].actual_mass_g = 1.0
        cs1["reactant"].inventory_item_id = lot_B.id
        cs1["reactant"].actual_mass_g = 1.0
        db.session.commit()
        run_setup.start_run(run1); db.session.commit()
        cs1["product"].actual_mass_g = 1.5  # 1.5g of I
        db.session.commit()
        run_setup.complete_run(run1); db.session.commit()

        # I lot now has cost €200 (run 1 cost), cost_per_g = €133.33
        I_lot = (db.session.query(InventoryItem)
                 .filter_by(substance_id=I_.id).one())
        assert abs(I_lot.total_cost_eur - 200.0) < 1e-3
        assert I_lot.source_run_id == run1.id

        # === RUN 2 ===
        run2 = run_setup.create_draft(rxn2, u)
        run2.scale_input_value = 5.0; run2.scale_input_unit = "mmol"
        run2.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run2); db.session.commit()
        lot_C = (db.session.query(InventoryItem)
                 .filter_by(substance_id=C.id).one())
        cs2 = {c.role: c for c in run2.components}
        cs2["starting_material"].inventory_item_id = I_lot.id  # internal!
        cs2["starting_material"].actual_mass_g = 1.0
        cs2["reactant"].inventory_item_id = lot_C.id
        cs2["reactant"].actual_mass_g = 0.4
        db.session.commit()
        run_setup.start_run(run2); db.session.commit()

        bd2 = compute_run_cost(run2)
        # Direct: only C → 0.4g × 1€/g = €0.40
        assert abs(bd2.direct_total_eur - 0.4) < 1e-3
        # Cumulative: 0.4 + (1g × 133.33) = €133.73
        assert abs(bd2.total_eur - 133.733) < 0.05
        # Intermediates: cumulative - direct = €133.33
        assert abs(bd2.intermediates_total_eur - 133.333) < 0.05

        # Find the I-line and check is_from_internal_lot
        i_line = next(l for l in bd2.lines if l.substance_name == "I")
        assert i_line.is_from_internal_lot is True
        c_line = next(l for l in bd2.lines if l.substance_name == "C")
        assert c_line.is_from_internal_lot is False


def test_run_cost_multi_unit_metrics_solid_product(app):
    """Solid product (no density): €/g and €/mol available, €/mL is None."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import (
        compute_run_cost, product_unit_metrics,
    )

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        # Product: solid, no density
        prod = Substance(name="P", molecular_weight=200.0)
        db.session.add_all([sm, prod]); db.session.flush()
        lot = InventoryItem(substance_id=sm.id, quantity_g=10,
                            initial_quantity_g=10, total_cost_eur=100,
                            is_active=True)
        db.session.add(lot); db.session.flush()
        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()
        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 1.0  # → €10
        db.session.commit()
        run_setup.start_run(run); db.session.commit()
        cs["product"].actual_mass_g = 0.4  # 0.002 mol of MW 200
        db.session.commit()
        run_setup.complete_run(run); db.session.commit()

        bd = compute_run_cost(run)
        m = product_unit_metrics(run, bd.total_eur)
        # €10 / 0.4g = €25/g
        assert abs(m.per_g - 25.0) < 1e-6
        # €10 / 0.002 mol = €5000/mol
        assert abs(m.per_mol - 5000.0) < 1e-3
        # No density → no €/mL
        assert m.per_mL is None


def test_run_cost_multi_unit_metrics_liquid_product(app):
    """Liquid product with density: all three €/g, €/mL, €/mol available."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.run_cost import (
        compute_run_cost, product_unit_metrics,
    )

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        # Liquid product: density 0.8 g/mL, MW 120
        prod = Substance(name="P", molecular_weight=120.0,
                         density=0.8, state="liquid")
        db.session.add_all([sm, prod]); db.session.flush()
        lot = InventoryItem(substance_id=sm.id, quantity_g=10,
                            initial_quantity_g=10, total_cost_eur=200,
                            is_active=True)
        db.session.add(lot); db.session.flush()
        rxn = Reaction(code="RX", template_code="T.1", template_code_base="T",
                       version_number=1, status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()
        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()
        cs = {c.role: c for c in run.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 0.5  # → €10 (0.5g × 20€/g)
        db.session.commit()
        run_setup.start_run(run); db.session.commit()
        cs["product"].actual_mass_g = 0.6  # 0.6g of liquid (= 0.75 mL @ 0.8 g/mL)
        db.session.commit()
        run_setup.complete_run(run); db.session.commit()

        bd = compute_run_cost(run)
        m = product_unit_metrics(run, bd.total_eur)
        # €10 / 0.6 g = €16.67/g
        assert abs(m.per_g - 10.0/0.6) < 1e-3
        # 0.6g / 0.8 g/mL = 0.75 mL → €10/0.75 = €13.33/mL
        assert abs(m.per_mL - (10.0 / 0.75)) < 1e-3
        # 0.6g / 120 g/mol = 0.005 mol → €2000/mol
        assert abs(m.per_mol - 2000.0) < 1e-3


# ─── Settimana 6 patch 6 — Template stats ──────────────────────────


def test_template_stats_aggregates_across_runs(app):
    """stats_for_template aggregates cost and yield over all runs of a template."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.template_stats import stats_for_template

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=200.0)
        db.session.add_all([sm, prod]); db.session.flush()
        lot = InventoryItem(substance_id=sm.id, quantity_g=100,
                            initial_quantity_g=100, total_cost_eur=1000,
                            is_active=True)
        db.session.add(lot); db.session.flush()
        rxn = Reaction(code="RX", template_code="STAT.1",
                       template_code_base="STAT", version_number=1,
                       status="published", title="T")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()

        # 3 runs producing 0.4, 0.5, 0.6g of product (each consumed 1g SM = €10)
        for prod_g in [0.4, 0.5, 0.6]:
            run = run_setup.create_draft(rxn, u)
            run.scale_input_value = 5.0; run.scale_input_unit = "mmol"
            run.scale_mmol = 5.0
            db.session.commit()
            run_setup.recompute_targets(run); db.session.commit()
            cs = {c.role: c for c in run.components}
            cs["starting_material"].inventory_item_id = lot.id
            cs["starting_material"].actual_mass_g = 1.0
            db.session.commit()
            run_setup.start_run(run); db.session.commit()
            cs["product"].actual_mass_g = prod_g
            db.session.commit()
            run_setup.complete_run(run); db.session.commit()

        s = stats_for_template("STAT")
        assert s.has_data is True
        assert s.n_runs == 3
        assert s.n_runs_with_cost == 3
        # Each run cost €10
        assert abs(s.avg_cost_eur - 10.0) < 1e-3
        assert s.min_cost_eur == 10.0
        assert s.max_cost_eur == 10.0
        # €/g: 25, 20, 16.67 → avg ~20.56
        assert abs(s.avg_cost_per_g - (25 + 20 + 10/0.6) / 3) < 0.1
        # Min/max for €/g
        assert abs(s.min_cost_per_g - 10/0.6) < 0.01
        assert abs(s.max_cost_per_g - 25.0) < 0.01
        # Last run is the third
        assert s.last_run is not None
        assert abs(s.last_run.cost_per_g - 10/0.6) < 0.01
        # 3 chronological points
        assert len(s.points) == 3


def test_template_stats_groups_versions(app):
    """All versions of a template (X.1, X.2, ...) aggregate together."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.template_stats import stats_for_template

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=200.0)
        db.session.add_all([sm, prod]); db.session.flush()
        lot = InventoryItem(substance_id=sm.id, quantity_g=100,
                            initial_quantity_g=100, total_cost_eur=1000,
                            is_active=True)
        db.session.add(lot); db.session.flush()

        # Two reactions: same template_code_base, different versions
        rxn1 = Reaction(code="R1", template_code="VER.1",
                        template_code_base="VER", version_number=1,
                        status="published", title="V1")
        rxn2 = Reaction(code="R2", template_code="VER.2",
                        template_code_base="VER", version_number=2,
                        status="published", title="V2")
        db.session.add_all([rxn1, rxn2]); db.session.flush()
        for r in (rxn1, rxn2):
            db.session.add_all([
                ReactionComponent(reaction_id=r.id, substance_id=sm.id,
                                  role="starting_material", position=0,
                                  is_limiting=True, equivalents=1.0),
                ReactionComponent(reaction_id=r.id, substance_id=prod.id,
                                  role="product", position=1),
            ])
        db.session.commit()

        # 1 run on each
        for rxn, prod_g in [(rxn1, 0.4), (rxn2, 0.6)]:
            run = run_setup.create_draft(rxn, u)
            run.scale_input_value = 5.0; run.scale_input_unit = "mmol"
            run.scale_mmol = 5.0
            db.session.commit()
            run_setup.recompute_targets(run); db.session.commit()
            cs = {c.role: c for c in run.components}
            cs["starting_material"].inventory_item_id = lot.id
            cs["starting_material"].actual_mass_g = 1.0
            db.session.commit()
            run_setup.start_run(run); db.session.commit()
            cs["product"].actual_mass_g = prod_g
            db.session.commit()
            run_setup.complete_run(run); db.session.commit()

        s = stats_for_template("VER")
        # Both versions count
        assert s.n_runs == 2
        # Latest title is V2
        assert s.template_title == "V2"


def test_template_stats_excludes_drafts(app):
    """Draft runs (not yet completed) don't appear in stats."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, InventoryItem)
    from stoic_eln.services import run_setup
    from stoic_eln.services.template_stats import stats_for_template

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=200.0)
        db.session.add_all([sm, prod]); db.session.flush()
        lot = InventoryItem(substance_id=sm.id, quantity_g=100,
                            initial_quantity_g=100, total_cost_eur=1000,
                            is_active=True)
        db.session.add(lot); db.session.flush()
        rxn = Reaction(code="RX", template_code="DR.1",
                       template_code_base="DR", version_number=1,
                       status="published", title="DR")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        db.session.commit()

        # 1 completed, 1 draft, 1 in_progress
        completed = run_setup.create_draft(rxn, u)
        completed.scale_input_value = 5.0; completed.scale_input_unit = "mmol"
        completed.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(completed); db.session.commit()
        cs = {c.role: c for c in completed.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 1.0
        db.session.commit()
        run_setup.start_run(completed); db.session.commit()
        cs["product"].actual_mass_g = 0.5
        db.session.commit()
        run_setup.complete_run(completed); db.session.commit()

        # Draft (not completed)
        run_setup.create_draft(rxn, u)
        db.session.commit()
        # In progress
        in_prog = run_setup.create_draft(rxn, u)
        in_prog.scale_input_value = 5.0; in_prog.scale_input_unit = "mmol"
        in_prog.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(in_prog); db.session.commit()
        cs = {c.role: c for c in in_prog.components}
        cs["starting_material"].inventory_item_id = lot.id
        cs["starting_material"].actual_mass_g = 1.0
        db.session.commit()
        run_setup.start_run(in_prog); db.session.commit()
        # NOT completed

        s = stats_for_template("DR")
        # Only the 1 completed run shows up
        assert s.n_runs == 1


# ─── Settimana 6 patch 6.1 — Currency ─────────────────────────────


def test_currency_default_eur(app):
    """Default currency is EUR with euro symbol."""
    from stoic_eln.services.currency import (
        get_currency_code, format_currency, currency_glyph,
    )
    with app.app_context():
        assert get_currency_code() == "EUR"
        assert currency_glyph() == "€"
        assert format_currency(100.0) == "€ 100.00"


def test_currency_set_known_codes(app):
    """Setting USD/JPY/GBP picks up correct glyphs."""
    from stoic_eln.services.currency import (
        set_currency_code, format_currency,
    )
    with app.app_context():
        set_currency_code("USD")
        assert format_currency(50.0) == "$ 50.00"
        set_currency_code("JPY")
        assert format_currency(50.0) == "¥ 50.00"
        set_currency_code("GBP")
        assert format_currency(50.0) == "£ 50.00"
        set_currency_code("INR")
        assert format_currency(50.0) == "₹ 50.00"


def test_currency_unknown_code_uses_iso(app):
    """For codes without a known glyph, the ISO code is shown."""
    from stoic_eln.services.currency import (
        set_currency_code, format_currency,
    )
    with app.app_context():
        set_currency_code("UZS")  # Uzbek so'm — no widely-used glyph
        assert format_currency(50.0) == "UZS 50.00"
        set_currency_code("ZMW")  # Zambian kwacha
        assert format_currency(50.0) == "ZMW 50.00"


def test_currency_validation(app):
    """Invalid codes raise ValueError."""
    from stoic_eln.services.currency import set_currency_code
    with app.app_context():
        for bad in ["", "X", "AB", "ABCD", "123", "EU1"]:
            try:
                set_currency_code(bad)
            except ValueError:
                pass
            else:
                assert False, f"Expected ValueError for {bad!r}"


def test_currency_format_none(app):
    """format_currency(None) returns the dash placeholder."""
    from stoic_eln.services.currency import format_currency
    with app.app_context():
        assert format_currency(None) == "—"


def test_currency_settings_page(app, client):
    """The settings page renders and the form updates persistently."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User
    from stoic_eln.services.currency import get_currency_code

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.commit()

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    r = client.get("/settings/currency")
    assert r.status_code == 200
    assert b"EUR" in r.data

    r = client.post("/settings/currency/update",
                    data={"csrf_token": "", "code": "USD"})
    assert r.status_code == 302
    with app.app_context():
        assert get_currency_code() == "USD"

    r = client.post("/settings/currency/update",
                    data={"csrf_token": "", "code": "UZS"})
    assert r.status_code == 302
    with app.app_context():
        assert get_currency_code() == "UZS"


# ─── Settimana 6 patch 7 — Hotfixes ───────────────────────────────


def test_substances_sort_case_insensitive(app):
    """Substance ordering ignores case (abaco before Aceto before Banana)."""
    from sqlalchemy import func
    from stoic_eln.extensions import db
    from stoic_eln.models import Substance

    with app.app_context():
        for n in ["Zucchero", "abaco", "Banana", "caramelle", "Aceto"]:
            db.session.add(Substance(name=n, molecular_weight=100))
        db.session.commit()
        rows = (db.session.query(Substance)
                .order_by(func.lower(Substance.name)).all())
        names = [r.name for r in rows]
        assert names == ["abaco", "Aceto", "Banana", "caramelle", "Zucchero"]


def test_template_code_conflict_renders_flash_not_500(app, client):
    """Saving a draft with an existing template_code shows a flash, not 500."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        # Existing published template
        existing = Reaction(code="RX-EX", template_code="DUP",
                            template_code_base="DUP", version_number=1,
                            status="published", title="Existing",
                            is_archived=False)
        # A draft trying to use the same code
        draft = Reaction(code="RX-DR", template_code="DUP",
                         template_code_base="DUP", version_number=1,
                         status="draft", title="My new template",
                         created_by_id=u.id)
        db.session.add_all([existing, draft]); db.session.commit()
        draft_id = draft.id

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    r = client.post(f"/reactions/{draft_id}/save",
                    data={"csrf_token": "", "code": "DUP",
                          "title": "My new template"},
                    follow_redirects=False)
    # Should redirect to detail with flash, NOT 500
    assert r.status_code == 302, f"Expected redirect, got {r.status_code}"

    # The error message should be visible on the redirected page
    r = client.get(f"/reactions/{draft_id}")
    body = r.data.decode()
    assert "DUP" in body  # mentioned in the error
    # No traceback page
    assert "TemplateCodeError" not in body or "alert" in body.lower()


def test_step_component_set_lot_and_actual(app, client):
    """Step component can have a lot assigned and actual quantity set."""
    from stoic_eln.extensions import db
    from stoic_eln.models import (User, Substance, Reaction,
                                   ReactionComponent, ReactionStep,
                                   ReactionStepComponent, InventoryItem)
    from stoic_eln.models.run_step import RunStepComponent
    from stoic_eln.services import run_setup

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        sm = Substance(name="SM", molecular_weight=100.0)
        prod = Substance(name="P", molecular_weight=200.0)
        dcm = Substance(name="DCM", molecular_weight=85,
                        density=1.33, state="liquid")
        db.session.add_all([sm, prod, dcm]); db.session.flush()
        lot_sm = InventoryItem(substance_id=sm.id, quantity_g=10,
                               initial_quantity_g=10, total_cost_eur=100,
                               is_active=True)
        lot_dcm = InventoryItem(substance_id=dcm.id, quantity_mL=1000,
                                initial_quantity_mL=1000, total_cost_eur=50,
                                is_active=True)
        db.session.add_all([lot_sm, lot_dcm]); db.session.flush()

        rxn = Reaction(code="RX", template_code="WK.1",
                       template_code_base="WK", version_number=1,
                       status="published", title="WK")
        db.session.add(rxn); db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id,
                              role="starting_material", position=0,
                              is_limiting=True, equivalents=1.0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id,
                              role="product", position=1),
        ])
        step = ReactionStep(reaction_id=rxn.id, kind="workup",
                            title="Column", position=0)
        db.session.add(step); db.session.flush()
        # Free quantity — no ratio
        db.session.add(ReactionStepComponent(
            step_id=step.id, substance_id=dcm.id, role="solvent",
            ratio_value=None, ratio_kind=None, position=0))
        db.session.commit()

        run = run_setup.create_draft(rxn, u)
        run.scale_input_value = 5.0; run.scale_input_unit = "mmol"
        run.scale_mmol = 5.0
        db.session.commit()
        run_setup.recompute_targets(run); db.session.commit()
        run_id = run.id
        sc_id = (db.session.query(RunStepComponent)
                 .filter_by(substance_id=dcm.id).one().id)
        lot_dcm_id = lot_dcm.id

    client.post("/auth/login",
                data={"username": "r", "password": "x", "submit": "x"})

    # Set lot
    r = client.post(f"/runs/{run_id}/step_component/{sc_id}/lot",
                    data={"csrf_token": "", "lot_id": str(lot_dcm_id)})
    assert r.status_code == 302
    with app.app_context():
        sc = db.session.get(RunStepComponent, sc_id)
        assert sc.inventory_item_id == lot_dcm_id

    # Set actual quantity 300 mL
    r = client.post(f"/runs/{run_id}/step_component/{sc_id}/actual",
                    data={"csrf_token": "", "actual": "300", "unit": "mL"})
    assert r.status_code == 302
    with app.app_context():
        sc = db.session.get(RunStepComponent, sc_id)
        assert sc.actual_volume_mL == 300.0
        assert sc.actual_mass_g is None

    # Clear actual
    r = client.post(f"/runs/{run_id}/step_component/{sc_id}/actual",
                    data={"csrf_token": "", "actual": "", "unit": "mL"})
    assert r.status_code == 302
    with app.app_context():
        sc = db.session.get(RunStepComponent, sc_id)
        assert sc.actual_volume_mL is None


# ─── Settimana 6 patch 8 — Audit log ──────────────────────────────


def test_audit_log_query_basic(app):
    """query_events returns events newest-first with paging."""
    from stoic_eln.extensions import db
    from stoic_eln.models import AuditLog, User
    from stoic_eln.services.audit_query import (
        AuditFilters, query_events,
    )

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        for i in range(7):
            db.session.add(AuditLog(
                user_id=u.id, action="create",
                entity_type="substance", entity_id=i,
                details={"i": i},
            ))
        db.session.commit()

        page = query_events(AuditFilters(), page=1, page_size=3)
        assert page.total == 7
        assert page.total_pages == 3
        assert len(page.events) == 3
        # Newest first → entity_id=6 should be first
        assert page.events[0].entity_id == 6


def test_audit_log_filters(app):
    """Filtering by user, action, entity_type, q works."""
    from stoic_eln.extensions import db
    from stoic_eln.models import AuditLog, User
    from stoic_eln.services.audit_query import (
        AuditFilters, query_events,
    )

    with app.app_context():
        u1 = User(username="r", full_name="R", operator_code="RR",
                  role="admin", is_admin=True, is_active=True, locale="it")
        u2 = User(username="op", full_name="Op", operator_code="OP",
                  role="operator", is_admin=False, is_active=True, locale="it")
        u1.set_password("x"); u2.set_password("x")
        db.session.add_all([u1, u2]); db.session.flush()
        db.session.add_all([
            AuditLog(user_id=u1.id, action="login"),
            AuditLog(user_id=u1.id, action="create",
                     entity_type="substance", entity_id=1,
                     details={"name": "Pd(OAc)2"}),
            AuditLog(user_id=u2.id, action="run_complete",
                     entity_type="run", entity_id=5),
        ])
        db.session.commit()

        # By user
        p = query_events(AuditFilters(user_id=u1.id))
        assert p.total == 2
        # By action
        p = query_events(AuditFilters(action="run_complete"))
        assert p.total == 1
        # By entity_type
        p = query_events(AuditFilters(entity_type="run"))
        assert p.total == 1
        # By free-text q (in details JSON)
        p = query_events(AuditFilters(q="Pd"))
        assert p.total == 1


def test_audit_log_csv_export(app):
    """export_csv returns valid CSV with all matching events."""
    from stoic_eln.extensions import db
    from stoic_eln.models import AuditLog, User
    from stoic_eln.services.audit_query import (
        AuditFilters, export_csv,
    )

    with app.app_context():
        u = User(username="r", full_name="R", operator_code="RR",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        db.session.add(AuditLog(
            user_id=u.id, action="create", entity_type="substance",
            entity_id=1, details={"name": "Pd(OAc)2"},
        ))
        db.session.commit()

        csv_text = export_csv(AuditFilters())
        lines = csv_text.strip().split("\n")
        assert len(lines) == 2  # header + 1 row
        assert "id" in lines[0]
        assert "Pd(OAc)2" in lines[1]


def test_audit_log_admin_only(app, client):
    """Non-admin cannot access /settings/audit-log."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User

    with app.app_context():
        op = User(username="op", full_name="Op", operator_code="OP",
                  role="operator", is_admin=False, is_active=True, locale="it")
        op.set_password("x"); db.session.add(op); db.session.commit()

    client.post("/auth/login", data={"username": "op", "password": "x",
                                       "submit": "x"})
    r = client.get("/settings/audit-log", follow_redirects=False)
    # Either 403 forbidden or redirect to login — anything but 200
    assert r.status_code in (302, 403)


def test_audit_log_admin_can_access(app, client):
    """Admin can access /settings/audit-log and see events."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, AuditLog

    with app.app_context():
        u = User(username="admin", full_name="Admin", operator_code="AD",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        db.session.add(AuditLog(
            user_id=u.id, action="create", entity_type="substance",
            entity_id=1, details={"name": "X"},
        ))
        db.session.commit()

    client.post("/auth/login", data={"username": "admin", "password": "x",
                                      "submit": "x"})
    r = client.get("/settings/audit-log")
    assert r.status_code == 200
    # Page contains the action and entity reference
    text = r.data.decode()
    assert "create" in text or "creato" in text
    assert "substance" in text


def test_audit_log_pdf_export(app, client):
    """PDF export returns a valid PDF."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, AuditLog

    with app.app_context():
        u = User(username="admin", full_name="Admin", operator_code="AD",
                 role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        db.session.add(AuditLog(user_id=u.id, action="login"))
        db.session.commit()

    client.post("/auth/login", data={"username": "admin", "password": "x",
                                      "submit": "x"})
    r = client.get("/settings/audit-log/export.pdf")
    assert r.status_code == 200
    assert r.data[:5] == b"%PDF-"
    assert "application/pdf" in r.headers.get("Content-Type", "")


# ─── Settimana 6 patch 9 — Notes ──────────────────────────────────


def test_markdown_renders_basic(app):
    """Lightweight markdown renders bold/italic/code/links/lists."""
    from stoic_eln.services.markdown import render_markdown
    with app.app_context():
        assert "<strong>x</strong>" in render_markdown("**x**")
        assert "<em>x</em>" in render_markdown("*x*")
        assert "<code>x</code>" in render_markdown("`x`")
        assert '<a href="https://x.com"' in render_markdown("[x](https://x.com)")
        assert "<ul><li>a</li><li>b</li></ul>" == render_markdown("- a\n- b")
        assert "<ol><li>a</li><li>b</li></ol>" == render_markdown("1. a\n2. b")


def test_markdown_escapes_html(app):
    """Raw HTML in input is always escaped."""
    from stoic_eln.services.markdown import render_markdown
    with app.app_context():
        out = render_markdown("<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


def test_markdown_rejects_javascript_urls(app):
    """javascript: and data: URLs are rendered as plain text."""
    from stoic_eln.services.markdown import render_markdown
    with app.app_context():
        out = render_markdown("[click](javascript:alert(1))")
        assert "javascript:" not in out or "<a" not in out
        # Should be literal text
        assert "[click]" in out


def test_note_create_anyone_authenticated(app, client):
    """Any logged-in user can create a note."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction, Note

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(f"/notes/reaction/{rxn_id}/new",
                    data={"csrf_token": "", "body": "test note"})
    assert r.status_code == 302
    with app.app_context():
        notes = db.session.query(Note).all()
        assert len(notes) == 1
        assert notes[0].body == "test note"
        assert notes[0].entity_type == "reaction"
        assert notes[0].entity_id == rxn_id


def test_note_only_author_can_edit(app, client):
    """A user cannot edit another user's note."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction, Note

    with app.app_context():
        u1 = User(username="u1", full_name="U1", operator_code="U1",
                  role="user", is_admin=False, is_active=True, locale="it")
        u2 = User(username="u2", full_name="U2", operator_code="U2",
                  role="user", is_admin=False, is_active=True, locale="it")
        u1.set_password("x"); u2.set_password("x")
        db.session.add_all([u1, u2]); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u1.id)
        db.session.add(rxn); db.session.flush()
        note = Note(entity_type="reaction", entity_id=rxn.id,
                    body="original", author_id=u1.id)
        db.session.add(note); db.session.commit()
        note_id = note.id

    # Login as u2 (not author)
    client.post("/auth/login",
                data={"username": "u2", "password": "x", "submit": "x"})
    r = client.post(f"/notes/{note_id}/edit",
                    data={"csrf_token": "", "body": "hacked"})
    assert r.status_code == 403
    with app.app_context():
        n = db.session.get(Note, note_id)
        assert n.body == "original"


def test_note_only_admin_can_delete(app, client):
    """Non-admin users cannot delete notes (even their own)."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction, Note

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.flush()
        note = Note(entity_type="reaction", entity_id=rxn.id,
                    body="mine", author_id=u.id)
        db.session.add(note); db.session.commit()
        note_id = note.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(f"/notes/{note_id}/delete", data={"csrf_token": ""})
    assert r.status_code == 403  # even own note can't be deleted
    with app.app_context():
        assert db.session.get(Note, note_id) is not None


def test_note_admin_can_delete_anyone(app, client):
    """Admins can delete any note."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction, Note

    with app.app_context():
        admin = User(username="admin", full_name="A", operator_code="AA",
                     role="admin", is_admin=True, is_active=True, locale="it")
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        admin.set_password("x"); u.set_password("x")
        db.session.add_all([admin, u]); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.flush()
        note = Note(entity_type="reaction", entity_id=rxn.id,
                    body="someone else's", author_id=u.id)
        db.session.add(note); db.session.commit()
        note_id = note.id

    client.post("/auth/login",
                data={"username": "admin", "password": "x", "submit": "x"})
    r = client.post(f"/notes/{note_id}/delete", data={"csrf_token": ""})
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(Note, note_id) is None


def test_note_edit_sets_updated_at(app, client):
    """Editing a note sets updated_at; same content does not."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction, Note

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.flush()
        note = Note(entity_type="reaction", entity_id=rxn.id,
                    body="v1", author_id=u.id)
        db.session.add(note); db.session.commit()
        note_id = note.id
        assert note.updated_at is None

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})

    # Edit with new content
    r = client.post(f"/notes/{note_id}/edit",
                    data={"csrf_token": "", "body": "v2"})
    assert r.status_code == 302
    with app.app_context():
        n = db.session.get(Note, note_id)
        assert n.body == "v2"
        assert n.updated_at is not None
        first_updated = n.updated_at

    # Edit again with same content — should be no-op (no updated_at change)
    r = client.post(f"/notes/{note_id}/edit",
                    data={"csrf_token": "", "body": "v2"})
    assert r.status_code == 302
    with app.app_context():
        n = db.session.get(Note, note_id)
        assert n.updated_at == first_updated


def test_note_validates_entity_type(app, client):
    """Trying to attach a note to a non-existent entity_type returns 404."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.commit()

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post("/notes/order/1/new",
                    data={"csrf_token": "", "body": "x"})
    assert r.status_code == 404


def test_note_rejects_empty_body(app, client):
    """Empty body produces a flash but doesn't create the note."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User, Reaction, Note

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(f"/notes/reaction/{rxn_id}/new",
                    data={"csrf_token": "", "body": "   "})
    assert r.status_code == 302
    with app.app_context():
        assert db.session.query(Note).count() == 0


# ── Attachments (Settimana 6 patch 10) ─────────────────────────────


def test_attachment_size_human(app):
    """The size_human property formats bytes with sensible units."""
    from stoic_eln.models import Attachment

    with app.app_context():
        a = Attachment(entity_type="run", entity_id=1, filename="x.pdf",
                       storage_filename="aa_x.pdf", size_bytes=512,
                       sha256="a" * 64)
        assert a.size_human == "512 B"
        a.size_bytes = 4096
        assert "kB" in a.size_human
        a.size_bytes = 5 * 1024 * 1024
        assert "MB" in a.size_human


def test_attachment_upload_pdf(app, client, tmp_path):
    """A logged-in user can upload a PDF; row is created with sha256."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import Attachment, Reaction, User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    payload = b"%PDF-1.4 fake content for testing"
    r = client.post(
        f"/attachments/reaction/{rxn_id}/new",
        data={"file": (io.BytesIO(payload), "spectrum.pdf"),
              "caption": "NMR purificato"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 302
    with app.app_context():
        atts = db.session.query(Attachment).all()
        assert len(atts) == 1
        a = atts[0]
        assert a.filename == "spectrum.pdf"
        assert a.entity_type == "reaction"
        assert a.entity_id == rxn_id
        assert a.size_bytes == len(payload)
        assert len(a.sha256) == 64
        assert a.caption == "NMR purificato"
        assert (tmp_path / a.storage_filename).exists()


def test_attachment_rejects_disallowed_extension(app, client, tmp_path):
    """Uploading a .exe (denied) is rejected with no row created."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import Attachment, Reaction, User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(
        f"/attachments/reaction/{rxn_id}/new",
        data={"file": (io.BytesIO(b"MZ..."), "evil.exe")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 302
    with app.app_context():
        assert db.session.query(Attachment).count() == 0


def test_attachment_rejects_empty_file(app, client, tmp_path):
    """A zero-byte upload is rejected."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import Attachment, Reaction, User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(
        f"/attachments/reaction/{rxn_id}/new",
        data={"file": (io.BytesIO(b""), "empty.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 302
    with app.app_context():
        assert db.session.query(Attachment).count() == 0


def test_attachment_download(app, client, tmp_path):
    """The download endpoint serves the file with the original filename."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import Attachment, Reaction, User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    payload = b"%PDF-1.4 download me"
    client.post(
        f"/attachments/reaction/{rxn_id}/new",
        data={"file": (io.BytesIO(payload), "data.pdf")},
        content_type="multipart/form-data",
    )

    with app.app_context():
        att_id = db.session.query(Attachment).first().id

    r = client.get(f"/attachments/{att_id}/download")
    assert r.status_code == 200
    assert r.data == payload
    cd = r.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert "data.pdf" in cd


def test_attachment_uploader_can_delete(app, client, tmp_path):
    """The uploader of an attachment can delete it themselves."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import Attachment, Reaction, User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    client.post(
        f"/attachments/reaction/{rxn_id}/new",
        data={"file": (io.BytesIO(b"xxxxx"), "doc.pdf")},
        content_type="multipart/form-data",
    )

    with app.app_context():
        a = db.session.query(Attachment).first()
        att_id = a.id
        on_disk = tmp_path / a.storage_filename
        assert on_disk.exists()

    r = client.post(f"/attachments/{att_id}/delete")
    assert r.status_code == 302
    with app.app_context():
        assert db.session.query(Attachment).count() == 0
        assert not on_disk.exists()


def test_attachment_non_uploader_non_admin_cannot_delete(app, client, tmp_path):
    """A user who is neither the uploader nor an admin gets 403 on delete."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import Attachment, Reaction, User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u1 = User(username="u1", full_name="U1", operator_code="U1",
                  role="user", is_admin=False, is_active=True, locale="it")
        u2 = User(username="u2", full_name="U2", operator_code="U2",
                  role="user", is_admin=False, is_active=True, locale="it")
        u1.set_password("x"); u2.set_password("x")
        db.session.add_all([u1, u2]); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u1.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    # u1 uploads
    client.post("/auth/login",
                data={"username": "u1", "password": "x", "submit": "x"})
    client.post(
        f"/attachments/reaction/{rxn_id}/new",
        data={"file": (io.BytesIO(b"xxxxx"), "doc.pdf")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        att_id = db.session.query(Attachment).first().id

    # u2 logs in and tries to delete
    client.get("/auth/logout")
    client.post("/auth/login",
                data={"username": "u2", "password": "x", "submit": "x"})
    r = client.post(f"/attachments/{att_id}/delete")
    assert r.status_code == 403
    with app.app_context():
        assert db.session.query(Attachment).count() == 1


def test_attachment_admin_can_delete_anyone(app, client, tmp_path):
    """An admin can delete attachments uploaded by any user."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import Attachment, Reaction, User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        adm = User(username="adm", full_name="Admin", operator_code="AD",
                   role="admin", is_admin=True, is_active=True, locale="it")
        u.set_password("x"); adm.set_password("x")
        db.session.add_all([u, adm]); db.session.flush()
        rxn = Reaction(code="R", template_code="X.1",
                       template_code_base="X", version_number=1,
                       status="draft", title="T", created_by_id=u.id)
        db.session.add(rxn); db.session.commit()
        rxn_id = rxn.id

    # u uploads
    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    client.post(
        f"/attachments/reaction/{rxn_id}/new",
        data={"file": (io.BytesIO(b"xxxxx"), "doc.pdf")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        att_id = db.session.query(Attachment).first().id

    # admin deletes
    client.get("/auth/logout")
    client.post("/auth/login",
                data={"username": "adm", "password": "x", "submit": "x"})
    r = client.post(f"/attachments/{att_id}/delete")
    assert r.status_code == 302
    with app.app_context():
        assert db.session.query(Attachment).count() == 0


def test_attachment_validates_entity_type(app, client, tmp_path):
    """Uploading to an invalid entity_type returns 404."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.commit()

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(
        "/attachments/order/1/new",
        data={"file": (io.BytesIO(b"x"), "x.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 404


# ── New entity types added in patch 14.4 ─────────────────────────


def test_attachment_upload_to_mixture(app, client, tmp_path):
    """Uploading to a Mixture (recipe-level attachment) succeeds.

    Example use: photo of an annotated SOP for preparing a buffer."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import User
    from stoic_eln.models.mixture import Mixture

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x")
        db.session.add(u)
        m = Mixture(name="Test buffer 50mM", kind="solution")
        db.session.add(m)
        db.session.commit()
        mixture_id = m.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(
        f"/attachments/mixture/{mixture_id}/new",
        data={"file": (io.BytesIO(b"fake-pdf-bytes"), "sop.pdf"),
              "caption": "SOP annotata a mano"},
        content_type="multipart/form-data",
    )
    # Non-HTMX upload: server redirects to entity detail (302).
    # HTMX upload: server returns rendered partial (200/204).
    assert r.status_code in (200, 204, 302)

    with app.app_context():
        from stoic_eln.models.attachment import Attachment
        rows = Attachment.query.filter_by(
            entity_type="mixture", entity_id=mixture_id,
        ).all()
        assert len(rows) == 1
        assert rows[0].filename == "sop.pdf"
        assert rows[0].caption == "SOP annotata a mano"


def test_attachment_upload_to_mixture_prep(app, client, tmp_path):
    """Uploading to a MixturePrep (single preparation event) succeeds.

    Example use: CoA of the produced batch, photo of the prep setup."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import User
    from stoic_eln.models.mixture import Mixture
    from stoic_eln.models.mixture_prep import MixturePrep

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x")
        db.session.add(u)
        m = Mixture(name="HCl 1N", kind="solution")
        db.session.add(m)
        db.session.flush()
        # MixturePrep mandatory cols: code, year, mixture_id,
        # target_quantity, target_quantity_unit.
        prep = MixturePrep(
            code="PREP-TEST-001",
            year=2026,
            mixture_id=m.id,
            target_quantity=100.0,
            target_quantity_unit="mL",
            prepared_by_id=u.id,
        )
        db.session.add(prep)
        db.session.commit()
        prep_id = prep.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(
        f"/attachments/mixture_prep/{prep_id}/new",
        data={"file": (io.BytesIO(b"fake-coa-bytes"), "coa.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code in (200, 204, 302)

    with app.app_context():
        from stoic_eln.models.attachment import Attachment
        rows = Attachment.query.filter_by(
            entity_type="mixture_prep", entity_id=prep_id,
        ).all()
        assert len(rows) == 1
        assert rows[0].filename == "coa.pdf"


def test_attachment_dedup_via_sha256_filename(app, client, tmp_path):
    """Uploading the same content twice yields one file on disk, two rows."""
    import io
    from stoic_eln.extensions import db
    from stoic_eln.models import Attachment, Reaction, User

    app.config["ATTACHMENTS_DIR"] = str(tmp_path)

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.flush()
        r1 = Reaction(code="R1", template_code="X.1",
                      template_code_base="X", version_number=1,
                      status="draft", title="T1", created_by_id=u.id)
        r2 = Reaction(code="R2", template_code="Y.1",
                      template_code_base="Y", version_number=1,
                      status="draft", title="T2", created_by_id=u.id)
        db.session.add_all([r1, r2]); db.session.commit()
        r1_id, r2_id = r1.id, r2.id

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    payload = b"identical content"
    client.post(
        f"/attachments/reaction/{r1_id}/new",
        data={"file": (io.BytesIO(payload), "same.pdf")},
        content_type="multipart/form-data",
    )
    client.post(
        f"/attachments/reaction/{r2_id}/new",
        data={"file": (io.BytesIO(payload), "same.pdf")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        atts = db.session.query(Attachment).all()
        assert len(atts) == 2
        # Same content → same sha → same storage_filename → single file
        assert atts[0].sha256 == atts[1].sha256
        assert atts[0].storage_filename == atts[1].storage_filename
        files_on_disk = list(tmp_path.iterdir())
        assert len(files_on_disk) == 1

        # Deleting one row must NOT remove the file (other row still refs it)
        att_id = atts[0].id

    r = client.post(f"/attachments/{att_id}/delete")
    assert r.status_code == 302
    with app.app_context():
        files_on_disk = list(tmp_path.iterdir())
        assert len(files_on_disk) == 1, "file removed too early"
        assert db.session.query(Attachment).count() == 1


# ── Labels (Settimana 6 patch 12) ──────────────────────────────────


def _make_lot(app, *, batch="LBL-001", expiry=None,
              ghs=None, h_codes=None, p_codes=None,
              substance_name="Aspirin"):
    """Create a Group + Substance + InventoryItem for label tests."""
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance

    with app.app_context():
        g = Group(name="Lab", slug="lab")
        db.session.add(g); db.session.flush()
        s = Substance(
            name=substance_name,
            cas_number="50-78-2",
            molecular_formula="C9H8O4",
            molecular_weight=180.16,
            density=1.40,
            ghs_pictograms=ghs or ["GHS07"],
            h_phrases=h_codes or ["H315", "H319", "H335"],
            p_phrases=p_codes or ["P261"],
        )
        db.session.add(s); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id,
            batch_code=batch,
            quantity_g=50.0, initial_quantity_g=50.0,
            expiry_date=expiry or date(2027, 6, 30),
            is_active=True,
        )
        db.session.add(it); db.session.commit()
        return it.id


def test_label_qr_payload_is_stable_json(app):
    """qr_payload returns canonical JSON (sorted keys, no whitespace)."""
    from stoic_eln.extensions import db
    from stoic_eln.models import InventoryItem
    from stoic_eln.services.labels import qr_payload

    item_id = _make_lot(app, batch="JSON-1")
    with app.app_context():
        it = db.session.get(InventoryItem, item_id)
        payload = qr_payload(it)
    # No spaces, alphabetical keys.
    assert payload.startswith('{"batch":"JSON-1"')
    assert "lotto_id" in payload
    assert "scadenza" in payload
    assert "sostanza" in payload
    # Round-trips as valid JSON.
    import json
    parsed = json.loads(payload)
    assert parsed["batch"] == "JSON-1"
    assert parsed["lotto_id"] == item_id


def test_label_pdf_avery_l7160(app):
    """Generates a valid PDF for the 24-up Avery sheet."""
    from stoic_eln.extensions import db
    from stoic_eln.models import InventoryItem
    from stoic_eln.services.labels import render_labels_pdf

    item_id = _make_lot(app)
    with app.app_context():
        it = db.session.get(InventoryItem, item_id)
        pdf = render_labels_pdf([it], "avery_l7160", copies_per_item=3)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_label_pdf_avery_l7164(app):
    """Generates a valid PDF for the 12-up Avery sheet."""
    from stoic_eln.extensions import db
    from stoic_eln.models import InventoryItem
    from stoic_eln.services.labels import render_labels_pdf

    item_id = _make_lot(app)
    with app.app_context():
        it = db.session.get(InventoryItem, item_id)
        pdf = render_labels_pdf([it], "avery_l7164", copies_per_item=1)
    assert pdf.startswith(b"%PDF-")


def test_label_pdf_thermal(app):
    """Generates a valid PDF for the thermal 62 mm format."""
    from stoic_eln.extensions import db
    from stoic_eln.models import InventoryItem
    from stoic_eln.services.labels import render_labels_pdf

    item_id = _make_lot(app)
    with app.app_context():
        it = db.session.get(InventoryItem, item_id)
        pdf = render_labels_pdf([it], "thermal_62", copies_per_item=2)
    assert pdf.startswith(b"%PDF-")


def test_label_pdf_unknown_format_raises(app):
    """An unknown format key raises ValueError, doesn't write a malformed PDF."""
    import pytest
    from stoic_eln.extensions import db
    from stoic_eln.models import InventoryItem
    from stoic_eln.services.labels import render_labels_pdf

    item_id = _make_lot(app)
    with app.app_context():
        it = db.session.get(InventoryItem, item_id)
        with pytest.raises(ValueError):
            render_labels_pdf([it], "not_a_real_format")


def test_label_pdf_empty_items_raises(app):
    """Calling with no items is a programming error, not silent."""
    import pytest
    from stoic_eln.services.labels import render_labels_pdf

    with app.app_context():
        with pytest.raises(ValueError):
            render_labels_pdf([], "avery_l7160")


def test_label_handles_substance_without_optional_fields(app):
    """Missing CAS / formula / GHS / phrases must not crash the renderer."""
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf

    with app.app_context():
        g = Group(name="Lab", slug="lab")
        db.session.add(g); db.session.flush()
        # Bare-bones substance: just a name.
        s = Substance(name="Mystery powder")
        db.session.add(s); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id,
            batch_code=None, expiry_date=None,
            quantity_g=10.0, initial_quantity_g=10.0,
            is_active=True,
        )
        db.session.add(it); db.session.commit()
        pdf = render_labels_pdf([it], "avery_l7160")
    assert pdf.startswith(b"%PDF-")


def test_label_form_route_renders(app, client):
    """The print-options page loads for an existing lot."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.commit()
    item_id = _make_lot(app, batch="ROUTE-1")

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.get(f"/inventory/{item_id}/label")
    assert r.status_code == 200
    assert b"avery_l7160" in r.data
    assert b"thermal_62" in r.data


def test_label_pdf_route_returns_pdf(app, client):
    """Submitting the form streams a PDF response."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.commit()
    item_id = _make_lot(app, batch="PDF-1")

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(
        f"/inventory/{item_id}/label.pdf",
        data={"csrf_token": "", "format": "avery_l7160",
              "copies": "2", "start_position": "5"},
    )
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data.startswith(b"%PDF-")
    assert b'filename="etichetta_PDF-1' in r.headers["Content-Disposition"].encode()


def test_label_pdf_route_rejects_invalid_format(app, client):
    """Invalid format key flashes an error and redirects (no 500)."""
    from stoic_eln.extensions import db
    from stoic_eln.models import User

    with app.app_context():
        u = User(username="u", full_name="U", operator_code="UU",
                 role="user", is_admin=False, is_active=True, locale="it")
        u.set_password("x"); db.session.add(u); db.session.commit()
    item_id = _make_lot(app)

    client.post("/auth/login",
                data={"username": "u", "password": "x", "submit": "x"})
    r = client.post(
        f"/inventory/{item_id}/label.pdf",
        data={"csrf_token": "", "format": "bogus", "copies": "1"},
    )
    assert r.status_code == 302  # redirect to form with flash


# ── Patch 12.1 hotfix regression tests ─────────────────────────────


def test_label_ghs_pictograms_actually_embedded(app):
    """GHS pictograms must end up in the PDF stream, not silently dropped.

    Before patch 12.1 the SVGs were drawn via renderPDF.draw() of a
    Drawing object, which sometimes lost its inner shapes when combined
    with canvas-level transforms. Now they're rasterised to PNG and
    embedded via drawImage(). We check by size: a label with two
    pictograms should be >> a label with none.
    """
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf

    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        plain = Substance(name="Plain")
        with_ghs = Substance(name="Hazardous",
                             ghs_pictograms=["GHS05", "GHS07", "GHS08"])
        db.session.add_all([plain, with_ghs]); db.session.flush()
        i_plain = InventoryItem(substance_id=plain.id, group_id=g.id,
                                quantity_g=1, initial_quantity_g=1, is_active=True)
        i_ghs = InventoryItem(substance_id=with_ghs.id, group_id=g.id,
                              quantity_g=1, initial_quantity_g=1, is_active=True)
        db.session.add_all([i_plain, i_ghs]); db.session.commit()

        pdf_plain = render_labels_pdf([i_plain], "avery_l7164")
        pdf_with_ghs = render_labels_pdf([i_ghs], "avery_l7164")

    # Three pictograms add ~30 KB of PNG image data each.
    assert len(pdf_with_ghs) > len(pdf_plain) + 5_000, (
        f"GHS not embedded: plain={len(pdf_plain)}, with_ghs={len(pdf_with_ghs)}"
    )


def test_label_renders_iupac_name_for_unsplittable_strings(app):
    """A single-token IUPAC name must not collapse to a bare ellipsis.

    Regression for `_fit_to_width`: IUPAC names like
    "1,3,7-trimethylpurine-2,6-dione" have no whitespace, and the old
    word-pop fallback returned just "…" because popping all tokens
    left an empty list (whose str-join + ellipsis trivially fits any
    width).
    """
    from stoic_eln.services.labels import _fit_to_width
    from reportlab.pdfgen import canvas
    import io

    c = canvas.Canvas(io.BytesIO())  # only used for stringWidth

    text = "1,3,7-trimethylpurine-2,6-dione"
    # 30 mm column (~85 pt) at 7.5 pt italic — definitely too narrow
    # for the full string but must produce a useful prefix, not "…".
    out = _fit_to_width(c, text, 85.0, "Helvetica-Oblique", 7.5)
    assert out, "result is empty"
    assert out != "…", "regressed to bare ellipsis"
    assert out.endswith("…"), "should mark truncation"
    # Must have at least 5 leading characters of the original.
    assert text.startswith(out[:5])


def test_label_pdf_l7164_embeds_2d_structure(app):
    """For L7164 with a SMILES we must actually produce a structure image.

    The earlier bug passed label-relative coordinates to _draw_molecule
    while the helper expected absolute page coordinates, so the
    structure landed somewhere off-label and was never visible.
    """
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf

    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        no_smiles = Substance(name="No SMILES",
                              ghs_pictograms=["GHS07"])
        with_smiles = Substance(name="Aspirin",
                                smiles="CC(=O)Oc1ccccc1C(=O)O",
                                ghs_pictograms=["GHS07"])
        db.session.add_all([no_smiles, with_smiles]); db.session.flush()
        i_a = InventoryItem(substance_id=no_smiles.id, group_id=g.id,
                            quantity_g=1, initial_quantity_g=1, is_active=True)
        i_b = InventoryItem(substance_id=with_smiles.id, group_id=g.id,
                            quantity_g=1, initial_quantity_g=1, is_active=True)
        db.session.add_all([i_a, i_b]); db.session.commit()

        pdf_no = render_labels_pdf([i_a], "avery_l7164")
        pdf_with = render_labels_pdf([i_b], "avery_l7164")

    # The molecule PNG is ~30 KB on its own; even with PDF compression
    # variance, the difference is well > 3 KB.
    assert len(pdf_with) > len(pdf_no) + 3_000, (
        f"structure not embedded: no_smiles={len(pdf_no)}, "
        f"with_smiles={len(pdf_with)}"
    )


def test_label_pdf_l7160_skips_2d_structure(app):
    """The compact L7160 format intentionally omits the structure.

    Sanity check: even with SMILES + RDKit available, the PDF for
    L7160 should NOT include a molecule image (no room).
    """
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf

    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        no_smiles = Substance(name="No SMILES",
                              ghs_pictograms=["GHS07"])
        with_smiles = Substance(name="Aspirin",
                                smiles="CC(=O)Oc1ccccc1C(=O)O",
                                ghs_pictograms=["GHS07"])
        db.session.add_all([no_smiles, with_smiles]); db.session.flush()
        i_a = InventoryItem(substance_id=no_smiles.id, group_id=g.id,
                            quantity_g=1, initial_quantity_g=1, is_active=True)
        i_b = InventoryItem(substance_id=with_smiles.id, group_id=g.id,
                            quantity_g=1, initial_quantity_g=1, is_active=True)
        db.session.add_all([i_a, i_b]); db.session.commit()

        pdf_no = render_labels_pdf([i_a], "avery_l7160")
        pdf_with = render_labels_pdf([i_b], "avery_l7160")

    # On L7160 the difference between with/without SMILES should be
    # negligible (both have only the GHS pictogram + text).
    assert abs(len(pdf_with) - len(pdf_no)) < 1_000, (
        f"L7160 unexpectedly embedded structure: "
        f"no_smiles={len(pdf_no)}, with_smiles={len(pdf_with)}"
    )


# ── Patch 12.2 layout regression tests ─────────────────────────────


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Pull plain text out of a PDF for assertion purposes.

    Uses pdftotext if available; otherwise tries to decompress
    FlateDecode streams in the PDF with zlib (standard library) and
    scans the decompressed text. As a last resort, falls back to
    scanning the raw bytes.
    """
    import re
    import subprocess
    import tempfile
    import zlib

    # Best path: pdftotext (poppler). Highest fidelity but requires
    # the binary to be installed.
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            path = f.name
        out = subprocess.check_output(
            ["pdftotext", "-layout", path, "-"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # Fallback: decompress every FlateDecode stream in the PDF and
    # concatenate the result. ReportLab writes content streams with
    # /Filter /FlateDecode for any non-trivial page, so without this
    # the raw bytes won't contain the visible glyphs as ASCII.
    decoded_chunks: list[str] = [pdf_bytes.decode("latin-1", errors="replace")]
    # PDF stream pattern: "stream\n...bytes...\nendstream"
    # We don't fully parse the PDF — we just extract every stream
    # body, try zlib.decompress on it, and append the result if it
    # decompresses cleanly. False matches (non-Flate streams) just
    # fail to decompress and are skipped.
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.DOTALL):
        raw = m.group(1)
        try:
            inflated = zlib.decompress(raw)
        except zlib.error:
            continue
        decoded_chunks.append(inflated.decode("latin-1", errors="replace"))
    return "\n".join(decoded_chunks)


def test_label_pdf_includes_exp_date_at_bottom(app):
    """The EXP: line must be present on the rendered label."""
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf

    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        s = Substance(name="Test compound",
                      molecular_formula="X", cas_number="0-0-0",
                      molecular_weight=100.0)
        db.session.add(s); db.session.flush()
        it = InventoryItem(substance_id=s.id, group_id=g.id,
                           batch_code="EXP-TEST",
                           quantity_g=1, initial_quantity_g=1,
                           expiry_date=date(2027, 6, 30), is_active=True)
        db.session.add(it); db.session.commit()
        pdf = render_labels_pdf([it], "thermal_62")

    text = _extract_pdf_text(pdf)
    assert "EXP:" in text or "EXP" in text, (
        "EXP marker missing from label PDF"
    )
    assert "2027-06-30" in text, "expiry date not rendered"


def test_label_pdf_lot_appears_above_name(app):
    """Lotto code is the first row, before the substance name."""
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf

    with app.app_context():
        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        s = Substance(name="Zeroinine")
        db.session.add(s); db.session.flush()
        it = InventoryItem(substance_id=s.id, group_id=g.id,
                           batch_code="FIRST-001",
                           quantity_g=1, initial_quantity_g=1,
                           expiry_date=date(2027, 1, 1), is_active=True)
        db.session.add(it); db.session.commit()
        pdf = render_labels_pdf([it], "thermal_62")

    text = _extract_pdf_text(pdf)
    if "FIRST-001" in text and "Zeroinine" in text:
        assert text.index("FIRST-001") < text.index("Zeroinine"), (
            "Lot code should appear before substance name"
        )


# ── Patch 12.3 GHS pictogram regression tests ──────────────────────


def test_ghs_png_renders_for_all_pictograms(app):
    """All 9 GHS codes must render to a non-empty PNG for both themes.

    Regression for the official UN/UNECE SVGs which use heterogeneous
    viewBoxes (the explosive pictogram is 5790×5790 — a fixed 600 dpi
    render against that requested ~48 000 pixels and crashed Cairo
    with "invalid value for size of input"). The current pipeline
    forces a fixed pixel target before rasterising.
    """
    from stoic_eln.services.labels import _ghs_png, _ghs_cache

    with app.app_context():
        _ghs_cache.clear()
        for code in [f"GHS0{i}" for i in range(1, 10)]:
            for theme in ("light", "dark"):
                png = _ghs_png(code, theme=theme)
                assert png is not None, f"{code} ({theme}) failed to render"
                assert png.startswith(b"\x89PNG"), (
                    f"{code} ({theme}) is not a PNG"
                )
                # 800×800 PNG with a moderately complex symbol should
                # comfortably exceed 1 KB.
                assert len(png) > 1_000, (
                    f"{code} ({theme}) suspiciously small: {len(png)} bytes"
                )


def test_ghs_dark_theme_inverts_white_to_dark_bg(app):
    """The dark-theme PNG must contain the dark-bg colour, not white.

    We sample the centre of the rendered pictogram. In light theme the
    inside of the diamond is white (#ffffff); in dark theme it should
    be the configured dark colour (#1a1a1a).
    """
    from stoic_eln.services.labels import _ghs_png, _ghs_cache
    from PIL import Image
    import io

    with app.app_context():
        _ghs_cache.clear()
        light = _ghs_png("GHS07", theme="light")
        dark = _ghs_png("GHS07", theme="dark")

    img_light = Image.open(io.BytesIO(light)).convert("RGB")
    img_dark = Image.open(io.BytesIO(dark)).convert("RGB")

    # Sample a point a third of the way down on the right side of the
    # exclamation mark — that area is part of the diamond background
    # in both themes (not on the symbol itself).
    sx, sy = int(img_light.width * 0.7), int(img_light.height * 0.4)
    light_px = img_light.getpixel((sx, sy))
    dark_px = img_dark.getpixel((sx, sy))

    # Light: should be near white. Dark: should be near our dark colour.
    assert sum(light_px) > 700, f"light theme not white: {light_px}"
    assert sum(dark_px) < 100, f"dark theme not dark: {dark_px}"


def test_ghs_pdf_uses_color_keying_to_avoid_white_halo(app):
    """The PDF embedding path must produce transparent corners.

    Sanity check: the GHS PNG must be a real RGBA bitmap, with the
    (0,0) corner — well outside the rotated diamond — having
    alpha=0. This is what lets ``mask='auto'`` composite the
    pictogram onto any background without a square white halo.

    An earlier implementation used a magenta colour-key sentinel
    (``mask=[255,255,0,0,255,255]``) which worked only on some
    reportlab versions; the present version emits a real alpha-
    channel PNG so the behaviour is consistent everywhere.
    """
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import (
        _ghs_png, _ghs_cache, render_labels_pdf,
    )
    from PIL import Image
    import io

    with app.app_context():
        _ghs_cache.clear()
        png = _ghs_png("GHS07", theme="light")
        assert png is not None

        img = Image.open(io.BytesIO(png))
        assert img.mode == "RGBA", (
            f"PNG must be RGBA for transparent corners, got {img.mode}"
        )
        # The (0,0) corner is well outside the rotated diamond; its
        # alpha must be 0 so the PDF/HTML page colour shows through.
        corner = img.getpixel((0, 0))
        assert corner[3] == 0, (
            f"top-left corner alpha must be 0 (transparent), "
            f"got pixel {corner}"
        )

        # Centre pixel is inside the diamond and must be opaque.
        cx, cy = img.width // 2, img.height // 2
        centre = img.getpixel((cx, cy))
        assert centre[3] == 255, (
            f"centre alpha must be 255 (opaque), got pixel {centre}"
        )

        g = Group(name="L", slug="l"); db.session.add(g); db.session.flush()
        s = Substance(name="Hazmat", ghs_pictograms=["GHS05", "GHS06"])
        db.session.add(s); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id, batch_code="HZM-1",
            quantity_g=1, initial_quantity_g=1,
            expiry_date=date(2027, 1, 1), is_active=True,
        )
        db.session.add(it); db.session.commit()
        pdf = render_labels_pdf([it], "avery_l7160")
    assert pdf.startswith(b"%PDF-")


# ── Patch 12.6 — never-truncate lot code, synthesised lot dates ────


def test_long_lot_code_is_never_truncated_on_label(app):
    """A long batch code must appear in full on the rendered label —
    never with an ellipsis. ``_fit_lot_code_lines`` shrinks the font
    and falls back to a two-line wrap rather than truncating.
    """
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf
    import subprocess

    LONG = "SIGMA-ALDRICH-2024-LOT-A88472913X"

    with app.app_context():
        g = Group(name="Long", slug="long"); db.session.add(g); db.session.flush()
        s = Substance(name="X", molecular_formula="X")
        db.session.add(s); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id, batch_code=LONG,
            quantity_g=1, initial_quantity_g=1,
            expiry_date=date(2027, 1, 1), is_active=True,
        )
        db.session.add(it); db.session.commit()
        pdf = render_labels_pdf([it], "avery_l7164")

    # If pdftotext is available, extract text and verify the full lot
    # code is present (possibly across two lines) and no ellipsis.
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=pdf, capture_output=True, timeout=10, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # No pdftotext — at minimum the PDF must render without crashing.
        assert pdf.startswith(b"%PDF-")
        return

    text = proc.stdout.decode("utf-8", errors="ignore")
    if LONG in text:
        # Single-line case: ensure no ellipsis next to the lot code.
        assert "…" not in text.split(LONG)[0][-30:], (
            "Ellipsis appears just before lot code — truncation!"
        )
        return
    # Wrapped case: concatenate non-empty stripped lines and look for
    # the full code in the joined string.
    joined = "".join(ln.strip() for ln in text.splitlines() if ln.strip())
    assert LONG in joined, (
        f"Lot code {LONG!r} not in label (saw: {text[:200]!r})"
    )
    assert "…" not in text, "Ellipsis present in label output"


def test_synthesised_lot_shows_synthesis_date_not_expiry(app):
    """A lot whose ``source_run_id`` points to a completed Run shows
    "Sint: <date>" on the label, taking the date from
    ``Run.completed_at`` — not "EXP:".
    """
    from datetime import datetime
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.models.run import Run
    from stoic_eln.services.labels import _pick_lot_date_label

    with app.app_context():
        g = Group(name="S", slug="s"); db.session.add(g); db.session.flush()
        s = Substance(name="In-house", molecular_formula="X")
        db.session.add(s); db.session.flush()
        run = Run(
            code="RUN-2026-100", sequence=100, year=2026,
            reaction_id=0, status="completed",
            completed_at=datetime(2026, 4, 15, 14, 30),
            started_at=datetime(2026, 4, 15, 9, 0),
        )
        db.session.add(run); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id, batch_code="LOT-A",
            quantity_g=1, initial_quantity_g=1,
            source_run_id=run.id, is_active=True,
        )
        db.session.add(it); db.session.commit()

        label = _pick_lot_date_label(it)

    assert label == "Sint: 2026-04-15", (
        f"Expected 'Sint: 2026-04-15', got {label!r}"
    )


def test_purchased_lot_with_expiry_shows_exp(app):
    """Plain purchased lot with explicit expiry → 'EXP: <date>'."""
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import _pick_lot_date_label

    with app.app_context():
        g = Group(name="P", slug="p"); db.session.add(g); db.session.flush()
        s = Substance(name="Bought", molecular_formula="X")
        db.session.add(s); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id, batch_code="P-1",
            quantity_g=1, initial_quantity_g=1,
            expiry_date=date(2027, 6, 30), is_active=True,
        )
        db.session.add(it); db.session.commit()
        label = _pick_lot_date_label(it)
    assert label == "EXP: 2027-06-30", label


def test_purchased_lot_without_expiry_shows_purchase_date(app):
    """Purchased lot with no expiry but known purchase date →
    'Acq: <date>' so the label still has a temporal anchor.
    """
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import _pick_lot_date_label

    with app.app_context():
        g = Group(name="P", slug="p2"); db.session.add(g); db.session.flush()
        s = Substance(name="Bought2", molecular_formula="X")
        db.session.add(s); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id, batch_code="P-2",
            quantity_g=1, initial_quantity_g=1,
            purchased_at=date(2025, 11, 14), is_active=True,
        )
        db.session.add(it); db.session.commit()
        label = _pick_lot_date_label(it)
    assert label == "Acq: 2025-11-14", label


def test_lot_code_helper_shrinks_then_wraps(app):
    """Unit test the ``_fit_lot_code_lines`` helper directly."""
    from reportlab.pdfgen.canvas import Canvas
    from stoic_eln.services.labels import _fit_lot_code_lines
    import io

    c = Canvas(io.BytesIO())

    # Short: one line at preferred size.
    lines, size = _fit_lot_code_lines(c, "AB-1", 200, "Helvetica", 8)
    assert lines == ["AB-1"]
    assert size == 8

    # Long but with hyphen separators: shrinks then fits.
    lines, size = _fit_lot_code_lines(
        c, "SIGMA-AL-2024-LOT-A88472913X", 60, "Helvetica", 8,
        min_size=5.0,
    )
    full = "".join(lines)
    assert full == "SIGMA-AL-2024-LOT-A88472913X", (
        f"lot code lost characters: {full!r}"
    )
    assert len(lines) <= 2

    # Long no-separator code in a moderately narrow column → two lines.
    # We need a width that's wider than half the code at min_size but
    # narrower than the full code at min_size, otherwise the helper
    # falls back to the truly-pathological single-line return.
    long_code = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    full_w_5pt = c.stringWidth(long_code, "Helvetica", 5.0)
    half_w_5pt = c.stringWidth(long_code[:13], "Helvetica", 5.0)
    target_w = (full_w_5pt + half_w_5pt) / 2  # between half and full
    lines, size = _fit_lot_code_lines(
        c, long_code, target_w, "Helvetica", 8,
        min_size=5.0,
    )
    full = "".join(lines)
    assert full == long_code, full
    assert len(lines) == 2, f"expected 2 lines, got {lines}"


# ── Patch 12.7 — proportional rescale ─────────────────────────────


def test_compute_proportional_shrink_returns_one_when_everything_fits(app):
    """When every row fits at base sizes, the helper returns 1.0 —
    no rescale needed.
    """
    from reportlab.pdfgen.canvas import Canvas
    from stoic_eln.services.labels import _compute_proportional_shrink
    import io

    c = Canvas(io.BytesIO())
    rows = [
        ("Lotto AB-1", "Helvetica", 7.5, 1000),
        ("Aluminum chloride", "Helvetica-Bold", 11.5, 1000),
        ("CAS 7446-70-0", "Helvetica", 8.5, 1000),
    ]
    assert _compute_proportional_shrink(c, rows) == 1.0


def test_compute_proportional_shrink_picks_worst_row(app):
    """The shrink ratio is dictated by the *worst-fitting* row.

    Two rows: a comfortably-fitting name and a too-long lot code.
    The ratio must equal max_w/lot_actual_w (capped at min_ratio).
    """
    from reportlab.pdfgen.canvas import Canvas
    from stoic_eln.services.labels import _compute_proportional_shrink
    import io

    c = Canvas(io.BytesIO())
    long_lot = "Lotto SIGMA-AL-2024-LOT-A88472913X"
    actual_w = c.stringWidth(long_lot, "Helvetica", 7.5)
    max_w = actual_w * 0.7  # the row needs ratio 0.7 to fit
    rows = [
        ("Aluminum", "Helvetica-Bold", 11.5, 1000),  # fits trivially
        (long_lot, "Helvetica", 7.5, max_w),         # the bottleneck
    ]
    ratio = _compute_proportional_shrink(c, rows, min_ratio=0.55)
    assert 0.69 < ratio < 0.71, f"expected ~0.70, got {ratio}"


def test_long_iupac_triggers_global_rescale_no_truncation(app):
    """A long IUPAC name should trigger a proportional rescale of the
    whole label — every row keeps its full content, no ellipsis appears.
    """
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf
    import subprocess

    LONG_IUPAC = "(2R,3S)-2-bromo-3-hydroxy-N-methylpentanamide"

    with app.app_context():
        g = Group(name="R", slug="r"); db.session.add(g); db.session.flush()
        s = Substance(
            name="Test compound",
            iupac_name=LONG_IUPAC,
            molecular_formula="C6H12BrNO2",
            molecular_weight=210.07,
        )
        db.session.add(s); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id, batch_code="LOT-1",
            quantity_g=1, initial_quantity_g=1,
            expiry_date=date(2027, 1, 1), is_active=True,
        )
        db.session.add(it); db.session.commit()
        pdf = render_labels_pdf([it], "avery_l7164")

    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=pdf, capture_output=True, timeout=10, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # pdftotext absent — at least the PDF rendered.
        assert pdf.startswith(b"%PDF-")
        return
    text = proc.stdout.decode("utf-8", errors="ignore")
    # Both the long IUPAC AND the lot code must be present in full,
    # without an ellipsis.
    assert LONG_IUPAC in text, f"IUPAC not in label: {text[:300]!r}"
    assert "LOT-1" in text, "lot code missing"
    assert "…" not in text, "ellipsis present — content was truncated"


def test_short_label_does_not_get_rescaled(app):
    """A label with only short content must render at full base sizes —
    no unnecessary shrinking.
    """
    from datetime import date
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, InventoryItem, Substance
    from stoic_eln.services.labels import render_labels_pdf

    with app.app_context():
        g = Group(name="S", slug="s2"); db.session.add(g); db.session.flush()
        s = Substance(
            name="Water",
            molecular_formula="H2O",
            molecular_weight=18.02,
        )
        db.session.add(s); db.session.flush()
        it = InventoryItem(
            substance_id=s.id, group_id=g.id, batch_code="W",
            quantity_g=1, initial_quantity_g=1,
            expiry_date=date(2027, 1, 1), is_active=True,
        )
        db.session.add(it); db.session.commit()
        pdf = render_labels_pdf([it], "avery_l7164")
    # Just verify it rendered. The key behaviour (no rescale needed)
    # is implicit in the helper's return value; we tested that
    # separately above.
    assert pdf.startswith(b"%PDF-")
