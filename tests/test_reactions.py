"""Tests for reactions blueprint, model, and stoichiometry service."""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.reaction import Reaction
from stoic_eln.models.reaction_component import ReactionComponent
from stoic_eln.models.substance import Substance
from stoic_eln.services import stoichiometry
from stoic_eln.services.code_generator import generate_reaction_code


# ─── Stoichiometry calculator ────────────────────────────────────────────────


def test_stoich_from_g():
    # 0.046 g of EtOH (MW=46.07, ρ=0.789) → 1 mmol, ~0.0583 mL
    q = stoichiometry.from_g(0.04607, mw=46.07, density=0.789)
    assert q.g == pytest.approx(0.04607)
    assert q.mmol == pytest.approx(1.0, abs=0.001)
    assert q.mL == pytest.approx(0.04607 / 0.789, abs=0.001)


def test_stoich_from_mL():
    # 1 mL of EtOH (ρ=0.789, MW=46.07) → 0.789 g → ~17.1 mmol
    q = stoichiometry.from_mL(1.0, mw=46.07, density=0.789)
    assert q.mL == pytest.approx(1.0)
    assert q.g == pytest.approx(0.789)
    assert q.mmol == pytest.approx(17.13, abs=0.05)


def test_stoich_from_mmol():
    # 1 mmol of MeOH (MW=32.04, ρ=0.792) → 0.03204 g → ~0.0405 mL
    q = stoichiometry.from_mmol(1.0, mw=32.04, density=0.792)
    assert q.mmol == pytest.approx(1.0)
    assert q.g == pytest.approx(0.03204, abs=0.001)
    assert q.mL == pytest.approx(0.0404, abs=0.001)


def test_stoich_from_equivalents_with_limiting():
    # 2 eq of catalyst, limiting reagent is at 1 mmol → catalyst is 2 mmol
    q = stoichiometry.from_equivalents(2.0, limiting_mmol=1.0, mw=100.0, density=None)
    assert q.equivalents == pytest.approx(2.0)
    assert q.mmol == pytest.approx(2.0)
    assert q.g == pytest.approx(0.2)
    assert q.mL is None


def test_stoich_from_equivalents_no_limiting():
    # If limiting_mmol is 0 or None, can't compute mmol
    q = stoichiometry.from_equivalents(2.0, limiting_mmol=None, mw=100.0, density=None)
    assert q.equivalents == 2.0
    assert q.mmol is None


def test_stoich_derive_priority():
    # When g is given, it wins over mmol
    q = stoichiometry.derive(mw=46.07, density=0.789, g=0.5, mmol=999)
    assert q.g == 0.5
    assert q.mmol == pytest.approx(0.5 * 1000 / 46.07, abs=0.01)


def test_stoich_handles_missing_mw():
    # No MW → can compute mL→g but not mmol
    q = stoichiometry.from_mL(1.0, mw=None, density=0.789)
    assert q.g == pytest.approx(0.789)
    assert q.mmol is None


# ─── Reaction model ──────────────────────────────────────────────────────────


def test_reaction_create(app):
    with app.app_context():
        r = Reaction(code="RX-2026-0001", title="Test reaction")
        db.session.add(r)
        db.session.commit()
        assert r.id is not None
        assert r.is_active is True


def test_reaction_code_unique(app):
    with app.app_context():
        a = Reaction(code="RX-2026-0001", title="A")
        db.session.add(a)
        db.session.commit()
        b = Reaction(code="RX-2026-0001", title="B")
        db.session.add(b)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


def test_generate_reaction_code_first(app):
    with app.app_context():
        code = generate_reaction_code()
        # Should be RX-{current_year}-0001
        from datetime import date

        assert code == f"RX-{date.today().year}-0001"


def test_generate_reaction_code_increments(app):
    with app.app_context():
        from datetime import date

        year = date.today().year

        # Insert a reaction with last code XXXX
        db.session.add(Reaction(code=f"RX-{year}-0001", title="A"))
        db.session.add(Reaction(code=f"RX-{year}-0002", title="B"))
        db.session.commit()

        next_code = generate_reaction_code()
        assert next_code == f"RX-{year}-0003"


def test_reaction_components_partitioning(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sm = Substance(name="EtOH", smiles="CCO")
        cat = Substance(name="Pd", smiles="[Pd]")
        prod = Substance(name="EtOAc", smiles="CCOC(=O)C")
        db.session.add_all([rxn, sm, cat, prod])
        db.session.flush()

        db.session.add_all(
            [
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=sm.id, role="starting_material", position=0
                ),
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=cat.id, role="catalyst", position=1
                ),
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=prod.id, role="product", position=2
                ),
            ]
        )
        db.session.commit()

        assert len(rxn.starting_materials) == 1
        assert len(rxn.reagents) == 1  # catalyst falls under reagents
        assert len(rxn.products) == 1
        assert rxn.reagents[0].role == "catalyst"


def test_reaction_derive_scheme_smiles(app):
    """Catalysts now render as text labels above the arrow (SciFinder
    style), not as drawn structures. So the SMILES used by SmilesDrawer
    contains only the LEFT and RIGHT reactants, never catalysts."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sm = Substance(name="EtOH", smiles="CCO")
        cat = Substance(name="Pd", smiles="[Pd]", molecular_formula="Pd")
        prod = Substance(name="EtOAc", smiles="CCOC(=O)C")
        db.session.add_all([rxn, sm, cat, prod])
        db.session.flush()

        db.session.add_all(
            [
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=sm.id, role="starting_material", position=0
                ),
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=cat.id, role="catalyst", position=1
                ),
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=prod.id, role="product", position=2
                ),
            ]
        )
        db.session.commit()

        scheme_smi = rxn.derive_scheme_smiles()
        # Catalysts no longer go INSIDE the SMILES — they become text
        # above the arrow. So we use the >> shortcut without agents.
        assert scheme_smi == "CCO>>CCOC(=O)C"

        # But the catalyst should appear in above_arrow_label as text
        scheme = rxn.derive_scheme()
        assert "Pd" in scheme["above_arrow_label"]
        assert len(scheme["agents_text"]) == 1
        assert scheme["agents_text"][0]["name"] == "Pd"
        assert len(scheme["agents_drawn"]) == 0


def test_reaction_derive_scheme_smiles_no_reagents(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sm = Substance(name="EtOH", smiles="CCO")
        prod = Substance(name="EtOAc", smiles="CCOC(=O)C")
        db.session.add_all([rxn, sm, prod])
        db.session.flush()
        db.session.add_all(
            [
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=sm.id, role="starting_material", position=0
                ),
                ReactionComponent(
                    reaction_id=rxn.id, substance_id=prod.id, role="product", position=1
                ),
            ]
        )
        db.session.commit()

        # No reagents → use the >> shortcut
        assert rxn.derive_scheme_smiles() == "CCO>>CCOC(=O)C"


def test_reaction_explicit_scheme_smiles_wins(app):
    with app.app_context():
        rxn = Reaction(
            code="RX-2026-0001",
            title="Test",
            scheme_smiles="CC.CC>>CCCC",
        )
        db.session.add(rxn)
        db.session.commit()
        # Even with no components, the explicit scheme is returned
        assert rxn.derive_scheme_smiles() == "CC.CC>>CCCC"


# ─── Routes ──────────────────────────────────────────────────────────────────


def _login(client, app):
    from stoic_eln.models.user import User

    with app.app_context():
        if db.session.query(User).filter_by(username="admin").first() is None:
            u = User(
                username="admin",
                full_name="Admin",
                operator_code="ADM",
                is_admin=True,
                is_active=True,
                locale="it",
            )
            u.set_password("password123")
            db.session.add(u)
            db.session.commit()
    client.post(
        "/auth/login", data={"username": "admin", "password": "password123", "submit": "Accedi"}
    )


def test_reactions_list_requires_auth(client):
    resp = client.get("/reactions/", follow_redirects=False)
    assert resp.status_code == 302


def test_reactions_list_renders(client, app):
    with app.app_context():
        db.session.add(Reaction(code="RX-2026-0001", title="Suzuki coupling"))
        db.session.commit()
    _login(client, app)
    resp = client.get("/reactions/")
    assert resp.status_code == 200
    assert b"RX-2026-0001" in resp.data
    assert b"Suzuki coupling" in resp.data


def test_reactions_search(client, app):
    with app.app_context():
        db.session.add_all(
            [
                Reaction(code="RX-2026-0001", title="Suzuki coupling"),
                Reaction(code="RX-2026-0002", title="Heck reaction"),
            ]
        )
        db.session.commit()
    _login(client, app)
    resp = client.get("/reactions/?q=suzuki")
    assert b"Suzuki" in resp.data
    assert b"Heck" not in resp.data


def test_reactions_search_by_substance_name(client, app):
    """Searching by a substance name should find reactions using that substance."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Some reaction")
        sub = Substance(name="UniqueSubstance123", smiles="CC")
        db.session.add_all([rxn, sub])
        db.session.flush()
        db.session.add(
            ReactionComponent(reaction_id=rxn.id, substance_id=sub.id, role="reactant", position=0)
        )
        db.session.commit()
    _login(client, app)
    resp = client.get("/reactions/?q=UniqueSubstance")
    assert b"RX-2026-0001" in resp.data


def test_reaction_create_post(client, app):
    """Creating a reaction is a two-step workflow:
       (1) POST /reactions/new → spawns a blank draft
       (2) POST /reactions/<id>/save with the header fields →
           validates, sets template_code, promotes to published.

    The old single-form-submit pattern (everything in one POST) was
    replaced when drafts were introduced — this test covers the new
    flow end-to-end."""
    _login(client, app)

    # Step 1: spawn draft
    resp = client.post("/reactions/new", follow_redirects=False)
    assert resp.status_code == 302
    # Pull the new draft id out of the redirect URL
    # (.../reactions/<id>)
    new_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    with app.app_context():
        draft = db.session.get(Reaction, new_id)
        assert draft is not None
        assert draft.status == "draft"
        # The draft is born with placeholder title
        assert draft.title == "Nuova reazione"

    # Step 2: save with real values
    resp = client.post(
        f"/reactions/{new_id}/save",
        data={
            "title": "My new reaction",
            "description": "Test rationale",
            "temperature_c": "80",
            "duration_hours": "16",
            "atmosphere": "N2",
            "template_code": "MNR",  # required to publish
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        rxn = db.session.get(Reaction, new_id)
        assert rxn is not None
        assert rxn.title == "My new reaction"
        assert rxn.code.startswith("RX-")
        assert rxn.temperature_c == 80.0
        assert rxn.atmosphere == "N2"
        assert rxn.status == "published"
        # template_code gets normalised — a fresh "MNR" becomes
        # "MNR.1" so future revisions can claim MNR.2, MNR.3, etc.
        assert rxn.template_code.startswith("MNR")


def test_reaction_detail(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="My reaction")
        db.session.add(rxn)
        db.session.commit()
        rid = rxn.id
    _login(client, app)
    resp = client.get(f"/reactions/{rid}")
    assert resp.status_code == 200
    assert b"RX-2026-0001" in resp.data


def test_add_component(client, app):
    """Adding a component to a reaction template registers the
    substance + role + equivalents. Absolute quantities
    (g/mL/mmol) are NOT stored at template level — they're
    computed per-run from the scale and equivalents."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sub = Substance(name="EtOH", smiles="CCO", molecular_weight=46.07, density=0.789)
        db.session.add_all([rxn, sub])
        db.session.commit()
        rid = rxn.id
        sid = sub.id

    _login(client, app)
    resp = client.post(
        f"/reactions/{rid}/components/new",
        data={
            "substance_id": str(sid),
            "mixture_id": "",  # XOR with substance_id
            "role": "starting_material",
            "equivalents": "1.0",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        components = db.session.query(ReactionComponent).filter_by(reaction_id=rid).all()
        assert len(components) == 1
        c = components[0]
        assert c.substance_id == sid
        assert c.role == "starting_material"
        # First SM with no others → auto-set as limiting with eq=1
        assert c.is_limiting is True
        assert c.equivalents == 1.0
        # Template-level: absolute quantities are intentionally None
        assert c.amount_g is None
        assert c.amount_mmol is None
        assert c.amount_mL is None


def test_add_component_with_equivalents_uses_limiting_mmol(client, app):
    """A second component added with equivalents persists the ratio,
    not absolute mmol. At template level we don't materialise mmol —
    that's a run-level computation that depends on scale_mmol.

    Test: SM added first (auto-limiting, eq=1), then catalyst at
    eq=0.05. The catalyst is NOT limiting and its eq is preserved."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sm = Substance(name="EtOH", smiles="CCO", molecular_weight=46.07)
        cat = Substance(name="Pd", smiles="[Pd]", molecular_weight=106.42)
        db.session.add_all([rxn, sm, cat])
        db.session.commit()
        rid, sm_id, cat_id = rxn.id, sm.id, cat.id

    _login(client, app)
    # First add SM → auto-limiting at eq=1
    client.post(
        f"/reactions/{rid}/components/new",
        data={
            "substance_id": str(sm_id),
            "mixture_id": "",
            "role": "starting_material",
            "equivalents": "1.0",
        },
    )
    # Then add catalyst with eq=0.05
    client.post(
        f"/reactions/{rid}/components/new",
        data={
            "substance_id": str(cat_id),
            "mixture_id": "",
            "role": "catalyst",
            "equivalents": "0.05",
        },
    )
    with app.app_context():
        components = (
            db.session.query(ReactionComponent)
            .filter_by(reaction_id=rid)
            .order_by(ReactionComponent.position)
            .all()
        )
        assert len(components) == 2
        sm_c, cat_c = components
        # SM is limiting at eq=1
        assert sm_c.is_limiting is True
        assert sm_c.equivalents == 1.0
        # Catalyst is non-limiting at eq=0.05
        assert cat_c.is_limiting is False
        assert cat_c.equivalents == pytest.approx(0.05)
        # Template-level: no absolute amounts
        assert cat_c.amount_mmol is None
        assert cat_c.amount_g is None


def test_delete_component(client, app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sub = Substance(name="EtOH")
        db.session.add_all([rxn, sub])
        db.session.flush()
        c = ReactionComponent(reaction_id=rxn.id, substance_id=sub.id, role="reactant", position=0)
        db.session.add(c)
        db.session.commit()
        cid = c.id
        rid = rxn.id

    _login(client, app)
    resp = client.post(f"/reactions/components/{cid}/delete", follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.query(ReactionComponent).filter_by(reaction_id=rid).count() == 0


def test_edit_component_inline(client, app):
    """The HTMX inline-edit endpoint accepts only template-level
    fields: equivalents, concentration_M, is_limiting.

    Absolute quantities (g/mL/mmol) live at the Run level — trying
    to edit them via this endpoint must be rejected with 400."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sub = Substance(name="EtOH", molecular_weight=46.07, density=0.789)
        db.session.add_all([rxn, sub])
        db.session.flush()
        c = ReactionComponent(
            reaction_id=rxn.id,
            substance_id=sub.id,
            role="reactant",  # not starting_material, so eq is editable
            position=0,
            equivalents=1.0,
            is_limiting=False,
        )
        db.session.add(c)
        db.session.commit()
        cid = c.id

    _login(client, app)

    # Valid: edit equivalents
    resp = client.post(
        f"/reactions/components/{cid}/edit",
        data={"field": "equivalents", "value": "1.5"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)
    with app.app_context():
        c = db.session.get(ReactionComponent, cid)
        assert c.equivalents == pytest.approx(1.5)

    # Invalid: try to edit amount_g → 400 (run-level field, not
    # editable at template level)
    resp = client.post(
        f"/reactions/components/{cid}/edit",
        data={"field": "amount_g", "value": "2.0"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_only_one_limiting_per_reaction(client, app):
    """Setting a component as limiting clears the flag on others."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        a = Substance(name="A")
        b = Substance(name="B")
        db.session.add_all([rxn, a, b])
        db.session.flush()
        ca = ReactionComponent(
            reaction_id=rxn.id,
            substance_id=a.id,
            role="reactant",
            position=0,
            is_limiting=True,
            amount_mmol=1.0,
        )
        cb = ReactionComponent(
            reaction_id=rxn.id, substance_id=b.id, role="reactant", position=1, is_limiting=False
        )
        db.session.add_all([ca, cb])
        db.session.commit()
        rid = rxn.id
        cb_id = cb.id

    _login(client, app)
    # Toggle B's limiting on
    client.post(
        f"/reactions/components/{cb_id}/edit",
        data={"field": "is_limiting", "value": "1"},
    )
    with app.app_context():
        components = db.session.query(ReactionComponent).filter_by(reaction_id=rid).all()
        limiting = [c for c in components if c.is_limiting]
        assert len(limiting) == 1
        assert limiting[0].id == cb_id
