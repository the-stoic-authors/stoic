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

        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id, role="starting_material", position=0),
            ReactionComponent(reaction_id=rxn.id, substance_id=cat.id, role="catalyst", position=1),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id, role="product", position=2),
        ])
        db.session.commit()

        assert len(rxn.starting_materials) == 1
        assert len(rxn.reagents) == 1  # catalyst falls under reagents
        assert len(rxn.products) == 1
        assert rxn.reagents[0].role == "catalyst"


def test_reaction_derive_scheme_smiles(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sm = Substance(name="EtOH", smiles="CCO")
        cat = Substance(name="Pd", smiles="[Pd]")
        prod = Substance(name="EtOAc", smiles="CCOC(=O)C")
        db.session.add_all([rxn, sm, cat, prod])
        db.session.flush()

        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id, role="starting_material", position=0),
            ReactionComponent(reaction_id=rxn.id, substance_id=cat.id, role="catalyst", position=1),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id, role="product", position=2),
        ])
        db.session.commit()

        scheme = rxn.derive_scheme_smiles()
        # Should be SM>cat>product
        assert scheme == "CCO>[Pd]>CCOC(=O)C"


def test_reaction_derive_scheme_smiles_no_reagents(app):
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sm = Substance(name="EtOH", smiles="CCO")
        prod = Substance(name="EtOAc", smiles="CCOC(=O)C")
        db.session.add_all([rxn, sm, prod])
        db.session.flush()
        db.session.add_all([
            ReactionComponent(reaction_id=rxn.id, substance_id=sm.id, role="starting_material", position=0),
            ReactionComponent(reaction_id=rxn.id, substance_id=prod.id, role="product", position=1),
        ])
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
    client.post("/auth/login", data={"username": "admin", "password": "password123", "submit": "Accedi"})


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
        db.session.add_all([
            Reaction(code="RX-2026-0001", title="Suzuki coupling"),
            Reaction(code="RX-2026-0002", title="Heck reaction"),
        ])
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
        db.session.add(ReactionComponent(reaction_id=rxn.id, substance_id=sub.id, role="reactant", position=0))
        db.session.commit()
    _login(client, app)
    resp = client.get("/reactions/?q=UniqueSubstance")
    assert b"RX-2026-0001" in resp.data


def test_reaction_create_post(client, app):
    _login(client, app)
    resp = client.post(
        "/reactions/new",
        data={
            "title": "My new reaction",
            "description": "Test rationale",
            "temperature_c": "80",
            "duration_hours": "16",
            "atmosphere": "N2",
            "submit": "Salva",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        rxn = db.session.query(Reaction).filter_by(title="My new reaction").first()
        assert rxn is not None
        assert rxn.code.startswith("RX-")
        assert rxn.temperature_c == 80.0
        assert rxn.atmosphere == "N2"


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
            "role": "starting_material",
            "amount_g": "1.0",
            "submit": "Aggiungi",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with app.app_context():
        components = db.session.query(ReactionComponent).filter_by(reaction_id=rid).all()
        assert len(components) == 1
        c = components[0]
        assert c.role == "starting_material"
        assert c.amount_g == 1.0
        # mmol auto-derived
        assert c.amount_mmol == pytest.approx(1.0 * 1000 / 46.07, abs=0.1)
        # First SM with no others → auto-set as limiting with eq=1
        assert c.is_limiting is True
        assert c.equivalents == 1.0


def test_add_component_with_equivalents_uses_limiting_mmol(client, app):
    """When a 2nd component is added with eq, mmol is derived from the limiting reagent."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sm = Substance(name="EtOH", smiles="CCO", molecular_weight=46.07)
        cat = Substance(name="Pd", smiles="[Pd]", molecular_weight=106.42)
        db.session.add_all([rxn, sm, cat])
        db.session.commit()
        rid, sm_id, cat_id = rxn.id, sm.id, cat.id

    _login(client, app)
    # First add SM with mmol=2 → auto-limiting
    client.post(
        f"/reactions/{rid}/components/new",
        data={"substance_id": str(sm_id), "role": "starting_material",
              "amount_mmol": "2.0", "submit": "Aggiungi"},
    )
    # Then add catalyst with eq=0.05 → expected mmol = 0.05 * 2 = 0.1
    client.post(
        f"/reactions/{rid}/components/new",
        data={"substance_id": str(cat_id), "role": "catalyst",
              "equivalents": "0.05", "submit": "Aggiungi"},
    )
    with app.app_context():
        components = db.session.query(ReactionComponent).filter_by(reaction_id=rid).order_by(ReactionComponent.position).all()
        cat_c = components[1]
        assert cat_c.equivalents == 0.05
        assert cat_c.amount_mmol == pytest.approx(0.1, abs=0.001)


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
    """The HTMX inline-edit endpoint updates a single field and recomputes the others."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        sub = Substance(name="EtOH", molecular_weight=46.07, density=0.789)
        db.session.add_all([rxn, sub])
        db.session.flush()
        c = ReactionComponent(
            reaction_id=rxn.id,
            substance_id=sub.id,
            role="starting_material",
            position=0,
            amount_g=1.0,
            amount_mmol=21.7,
            is_limiting=True,
        )
        db.session.add(c)
        db.session.commit()
        cid = c.id

    _login(client, app)
    # Update g to 2.0 → mmol should auto-recompute
    resp = client.post(
        f"/reactions/components/{cid}/edit",
        data={"field": "amount_g", "value": "2.0"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)
    with app.app_context():
        c = db.session.get(ReactionComponent, cid)
        assert c.amount_g == 2.0
        assert c.amount_mmol == pytest.approx(2.0 * 1000 / 46.07, abs=0.1)
        assert c.amount_mL == pytest.approx(2.0 / 0.789, abs=0.01)


def test_only_one_limiting_per_reaction(client, app):
    """Setting a component as limiting clears the flag on others."""
    with app.app_context():
        rxn = Reaction(code="RX-2026-0001", title="Test")
        a = Substance(name="A")
        b = Substance(name="B")
        db.session.add_all([rxn, a, b])
        db.session.flush()
        ca = ReactionComponent(reaction_id=rxn.id, substance_id=a.id, role="reactant",
                               position=0, is_limiting=True, amount_mmol=1.0)
        cb = ReactionComponent(reaction_id=rxn.id, substance_id=b.id, role="reactant",
                               position=1, is_limiting=False)
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
