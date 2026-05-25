"""Tests for the mixture preparation service (patch 13.2)."""

from __future__ import annotations

import pytest

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    InventoryItem,
    Mixture,
    MixtureComponent,
    Substance,
)
from stoic_eln.services.prep_service import (
    ConsumptionInput,
    PrepInput,
    execute_preparation,
    suggest_consumptions,
)


def _setup_hcl_dilution_lab():
    """Helper: pure HCl + Water substances, an HCl 12N mixture +
    its stock lot, an HCl 6N target mixture, a water lot.

    MUST be called inside an active ``app.app_context()``. Returns a
    dict of object IDs (not instances) — caller re-fetches via
    ``db.session.get(...)`` in the same context, so we don't run into
    DetachedInstanceError between contexts.
    """
    g = Group(name="Lab", slug="lab")
    db.session.add(g)
    db.session.flush()

    hcl = Substance(name="HCl", molecular_formula="HCl", ghs_pictograms=["GHS05", "GHS07"])
    h2o = Substance(name="Water", molecular_formula="H2O")
    db.session.add_all([hcl, h2o])
    db.session.flush()

    m_12n = Mixture(
        name="HCl 12N", kind="solution", primary_concentration=12.0, primary_concentration_unit="N"
    )
    m_12n.components = [
        MixtureComponent(
            substance_id=hcl.id,
            role="solute",
            concentration=12.0,
            concentration_unit="N",
            position=0,
        ),
        MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
    ]
    m_6n = Mixture(
        name="HCl 6N", kind="solution", primary_concentration=6.0, primary_concentration_unit="N"
    )
    m_6n.components = [
        MixtureComponent(
            substance_id=hcl.id,
            role="solute",
            concentration=12.0,
            concentration_unit="N",
            position=0,
        ),
        MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
    ]
    db.session.add_all([m_12n, m_6n])
    db.session.flush()

    stock_hcl = InventoryItem(
        mixture_id=m_12n.id,
        group_id=g.id,
        batch_code="HCL12N-001",
        quantity_mL=5000.0,
        initial_quantity_mL=5000.0,
        is_active=True,
    )
    stock_water = InventoryItem(
        substance_id=h2o.id,
        group_id=g.id,
        batch_code="H2O-001",
        quantity_mL=20000.0,
        initial_quantity_mL=20000.0,
        is_active=True,
    )
    db.session.add_all([stock_hcl, stock_water])
    db.session.commit()
    return {
        "m_12n_id": m_12n.id,
        "m_6n_id": m_6n.id,
        "hcl_id": hcl.id,
        "h2o_id": h2o.id,
        "stock_hcl_id": stock_hcl.id,
        "stock_water_id": stock_water.id,
        "stock_hcl_qty_initial": stock_hcl.quantity_mL,
    }


def test_suggest_dilution_math(app):
    """4 L HCl 6N should propose 2 L HCl 12N + 2 L H2O."""
    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        m_6n = db.session.get(Mixture, ctx["m_6n_id"])
        suggestion = suggest_consumptions(
            mixture=m_6n,
            target_quantity=4,
            target_unit="L",
        )
        rows_by_role = {r.role: r for r in suggestion.rows}
    assert "solute" in rows_by_role
    assert "solvent" in rows_by_role
    assert rows_by_role["solute"].suggested_quantity == 2.0
    assert rows_by_role["solvent"].suggested_quantity == 2.0
    assert rows_by_role["solute"].suggested_unit == "L"


def test_suggest_finds_mixture_lot_as_solute_source(app):
    """When asked for HCl as solute, must find the HCl 12N mixture lot
    (not just pure-HCl substance lots, of which there are none).
    """
    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        m_6n = db.session.get(Mixture, ctx["m_6n_id"])
        suggestion = suggest_consumptions(
            mixture=m_6n,
            target_quantity=4,
            target_unit="L",
        )
        solute_row = next(r for r in suggestion.rows if r.role == "solute")
        assert solute_row.suggested_lot_id == ctx["stock_hcl_id"]
        assert any(l.id == ctx["stock_hcl_id"] for l in solute_row.available_lots)


def test_suggest_warns_when_no_lots(app):
    """Mixture with components but no precursor lots: warning emitted."""
    with app.app_context():
        g = Group(name="Empty", slug="empty")
        db.session.add(g)
        db.session.flush()
        s1 = Substance(name="Z")
        s2 = Substance(name="Y")
        db.session.add_all([s1, s2])
        db.session.flush()
        m = Mixture(
            name="Mix Z 1M",
            kind="solution",
            primary_concentration=1.0,
            primary_concentration_unit="M",
        )
        m.components = [
            MixtureComponent(
                substance_id=s1.id,
                role="solute",
                concentration=10.0,
                concentration_unit="M",
                position=0,
            ),
            MixtureComponent(substance_id=s2.id, role="solvent", position=1),
        ]
        db.session.add(m)
        db.session.commit()
        suggestion = suggest_consumptions(
            mixture=m,
            target_quantity=1,
            target_unit="L",
        )
    assert any("Nessun lotto" in w for w in suggestion.warnings)


def test_execute_preparation_decrements_stocks_and_creates_lot(app):
    """End-to-end: execute_preparation scales stocks and produces the
    expected output lot."""
    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        inp = PrepInput(
            mixture_id=ctx["m_6n_id"],
            target_quantity=4.0,
            target_quantity_unit="L",
            consumptions=[
                ConsumptionInput(
                    inventory_item_id=ctx["stock_hcl_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["stock_water_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
            ],
            output_batch_code=None,
            output_location="Shelf A",
            output_expiry_date=None,
            output_notes=None,
            prepared_by_id=None,
        )
        prep = execute_preparation(inp)
        prep_id = prep.id

        # Reload everything fresh in the same session
        prep = db.session.get(type(prep), prep_id)
        stock_hcl = db.session.get(InventoryItem, ctx["stock_hcl_id"])
        stock_water = db.session.get(InventoryItem, ctx["stock_water_id"])

        assert stock_hcl.quantity_mL == 3000.0
        assert stock_water.quantity_mL == 18000.0
        assert prep.output_lot is not None
        assert prep.output_lot.quantity_mL == 4000.0
        assert prep.output_lot.mixture_id == ctx["m_6n_id"]
        assert prep.output_lot.substance_id is None
        assert prep.output_lot.batch_code == prep.code
        assert prep.code.startswith("HCL6N-")
        assert len(prep.consumptions) == 2


def test_execute_preparation_rejects_overdraft(app):
    """If a precursor lot lacks the requested quantity, the prep
    raises and nothing is committed."""
    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        before_hcl = ctx["stock_hcl_qty_initial"]

        inp = PrepInput(
            mixture_id=ctx["m_6n_id"],
            target_quantity=20.0,
            target_quantity_unit="L",
            consumptions=[
                ConsumptionInput(
                    inventory_item_id=ctx["stock_hcl_id"],
                    quantity_consumed=10.0,
                    quantity_unit="L",
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["stock_water_id"],
                    quantity_consumed=10.0,
                    quantity_unit="L",
                ),
            ],
            output_batch_code=None,
            output_location=None,
            output_expiry_date=None,
            output_notes=None,
            prepared_by_id=None,
        )
        with pytest.raises(ValueError, match="servono"):
            execute_preparation(inp)

        # Need a fresh session — the failed transaction may have
        # left things in an inconsistent local state.
        db.session.rollback()
        stock_hcl = db.session.get(InventoryItem, ctx["stock_hcl_id"])
        assert stock_hcl.quantity_mL == before_hcl


def test_execute_preparation_custom_batch_code(app):
    """A custom output_batch_code is used verbatim."""
    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        inp = PrepInput(
            mixture_id=ctx["m_6n_id"],
            target_quantity=2.0,
            target_quantity_unit="L",
            consumptions=[
                ConsumptionInput(
                    inventory_item_id=ctx["stock_hcl_id"],
                    quantity_consumed=1.0,
                    quantity_unit="L",
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["stock_water_id"],
                    quantity_consumed=1.0,
                    quantity_unit="L",
                ),
            ],
            output_batch_code="MY-CUSTOM-001",
            output_location=None,
            output_expiry_date=None,
            output_notes=None,
            prepared_by_id=None,
        )
        prep = execute_preparation(inp)
        assert prep.output_lot.batch_code == "MY-CUSTOM-001"
        assert prep.code == "MY-CUSTOM-001"


def test_execute_preparation_eluent_pct(app):
    """Eluent A 95:5 hexane:EtOAc — 1 L target → 950 mL hexane + 50 mL EtOAc."""
    with app.app_context():
        g = Group(name="L3", slug="l3")
        db.session.add(g)
        db.session.flush()
        hex_ = Substance(name="Hexane", molecular_formula="C6H14")
        etoac = Substance(name="EtOAc", molecular_formula="C4H8O2")
        db.session.add_all([hex_, etoac])
        db.session.flush()

        m = Mixture(name="Eluent A", kind="eluent")
        m.components = [
            MixtureComponent(
                substance_id=hex_.id,
                role="cosolvent",
                concentration=95.0,
                concentration_unit="%v/v",
                position=0,
            ),
            MixtureComponent(
                substance_id=etoac.id,
                role="cosolvent",
                concentration=5.0,
                concentration_unit="%v/v",
                position=1,
            ),
        ]
        db.session.add(m)
        db.session.flush()

        lot_hex = InventoryItem(
            substance_id=hex_.id,
            group_id=g.id,
            batch_code="HEX-1",
            quantity_mL=2000.0,
            initial_quantity_mL=2000.0,
            is_active=True,
        )
        lot_eto = InventoryItem(
            substance_id=etoac.id,
            group_id=g.id,
            batch_code="ETO-1",
            quantity_mL=500.0,
            initial_quantity_mL=500.0,
            is_active=True,
        )
        db.session.add_all([lot_hex, lot_eto])
        db.session.commit()

        suggestion = suggest_consumptions(
            mixture=m,
            target_quantity=1,
            target_unit="L",
        )

    rows = {r.substance_name: r for r in suggestion.rows}
    # 95% of 1 L = 950 mL = 0.95 L
    assert abs(rows["Hexane"].suggested_quantity - 0.95) < 1e-6
    assert abs(rows["EtOAc"].suggested_quantity - 0.05) < 1e-6


# ── Patch 13.2.1 — ratio, vol%, dynamic stock concentration ─────


def test_suggest_ratio_parts_5_to_2(app):
    """EtOAc/PE 5:2 with target 7 L → 5 L EtOAc + 2 L PE."""
    with app.app_context():
        g = Group(name="R", slug="r")
        db.session.add(g)
        db.session.flush()
        etoac = Substance(name="EtOAc", molecular_formula="C4H8O2")
        pe = Substance(name="Petroleum ether", molecular_formula="-")
        db.session.add_all([etoac, pe])
        db.session.flush()

        m = Mixture(name="EtOAc/PE 5:2", kind="eluent")
        m.components = [
            MixtureComponent(
                substance_id=etoac.id,
                role="cosolvent",
                concentration=5.0,
                concentration_unit="ratio",
                position=0,
            ),
            MixtureComponent(
                substance_id=pe.id,
                role="cosolvent",
                concentration=2.0,
                concentration_unit="ratio",
                position=1,
            ),
        ]
        db.session.add(m)
        db.session.flush()

        # Stock lots
        for sub, qty in [(etoac, 10000.0), (pe, 10000.0)]:
            db.session.add(
                InventoryItem(
                    substance_id=sub.id,
                    group_id=g.id,
                    batch_code=f"{sub.name[:3].upper()}-1",
                    quantity_mL=qty,
                    initial_quantity_mL=qty,
                    is_active=True,
                )
            )
        db.session.commit()

        suggestion = suggest_consumptions(
            mixture=m,
            target_quantity=7,
            target_unit="L",
        )

    rows_by_name = {r.substance_name: r for r in suggestion.rows}
    # 5/(5+2) × 7 = 5.0 L EtOAc; 2/(5+2) × 7 = 2.0 L PE
    assert abs(rows_by_name["EtOAc"].suggested_quantity - 5.0) < 1e-6
    assert abs(rows_by_name["Petroleum ether"].suggested_quantity - 2.0) < 1e-6
    assert rows_by_name["EtOAc"].suggested_unit == "L"


def test_suggest_ratio_three_components(app):
    """A:B:C = 1:2:3, target 12 L → 2 L + 4 L + 6 L."""
    with app.app_context():
        g = Group(name="R3", slug="r3")
        db.session.add(g)
        db.session.flush()
        a = Substance(name="A")
        b = Substance(name="B")
        c = Substance(name="C")
        db.session.add_all([a, b, c])
        db.session.flush()

        m = Mixture(name="A:B:C 1:2:3", kind="other")
        m.components = [
            MixtureComponent(
                substance_id=a.id,
                role="cosolvent",
                concentration=1.0,
                concentration_unit="ratio",
                position=0,
            ),
            MixtureComponent(
                substance_id=b.id,
                role="cosolvent",
                concentration=2.0,
                concentration_unit="ratio",
                position=1,
            ),
            MixtureComponent(
                substance_id=c.id,
                role="cosolvent",
                concentration=3.0,
                concentration_unit="ratio",
                position=2,
            ),
        ]
        db.session.add(m)
        db.session.flush()
        for sub in (a, b, c):
            db.session.add(
                InventoryItem(
                    substance_id=sub.id,
                    group_id=g.id,
                    quantity_mL=20000.0,
                    initial_quantity_mL=20000.0,
                    is_active=True,
                )
            )
        db.session.commit()

        suggestion = suggest_consumptions(
            mixture=m,
            target_quantity=12,
            target_unit="L",
        )

    rows_by_name = {r.substance_name: r for r in suggestion.rows}
    assert abs(rows_by_name["A"].suggested_quantity - 2.0) < 1e-6
    assert abs(rows_by_name["B"].suggested_quantity - 4.0) < 1e-6
    assert abs(rows_by_name["C"].suggested_quantity - 6.0) < 1e-6


def test_suggest_vol_pct_dilution_from_concentrated(app):
    """EtOH 50% v/v from EtOH 95% v/v + water, 1 L target.

    Math: V_stock = 1 L × 50 / 95 ≈ 0.5263 L; V_solvent = 1 - 0.5263.

    Critical: the stock concentration (95%) must come from the
    precursor lot's mixture, NOT from the recipe component (which
    we leave open here to confirm the dynamic-read behaviour).
    """
    with app.app_context():
        g = Group(name="V", slug="v")
        db.session.add(g)
        db.session.flush()
        etoh = Substance(name="EtOH", molecular_formula="C2H6O")
        h2o = Substance(name="Water", molecular_formula="H2O")
        db.session.add_all([etoh, h2o])
        db.session.flush()

        # Precursor mixture: EtOH 95% v/v in water (a commercial stock)
        m_95 = Mixture(
            name="EtOH 95% v/v",
            kind="solution",
            primary_concentration=95.0,
            primary_concentration_unit="%v/v",
            primary_solvent_id=h2o.id,
        )
        m_95.components = [
            MixtureComponent(
                substance_id=etoh.id,
                role="solute",
                concentration=95.0,
                concentration_unit="%v/v",
                position=0,
            ),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_95)
        db.session.flush()

        # Target mixture: EtOH 50% v/v. Crucially, the solute
        # component's concentration is LEFT BLANK to force the
        # system to read from the lot.
        m_50 = Mixture(
            name="EtOH 50% v/v",
            kind="solution",
            primary_concentration=50.0,
            primary_concentration_unit="%v/v",
            primary_solvent_id=h2o.id,
        )
        m_50.components = [
            MixtureComponent(
                substance_id=etoh.id,
                role="solute",
                concentration=None,
                concentration_unit=None,
                position=0,
            ),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_50)
        db.session.flush()

        # Lots
        stock_etoh = InventoryItem(
            mixture_id=m_95.id,
            group_id=g.id,
            batch_code="ETOH95-001",
            quantity_mL=2000.0,
            initial_quantity_mL=2000.0,
            is_active=True,
        )
        stock_h2o = InventoryItem(
            substance_id=h2o.id,
            group_id=g.id,
            batch_code="H2O-001",
            quantity_mL=20000.0,
            initial_quantity_mL=20000.0,
            is_active=True,
        )
        db.session.add_all([stock_etoh, stock_h2o])
        db.session.commit()

        suggestion = suggest_consumptions(
            mixture=m_50,
            target_quantity=1,
            target_unit="L",
        )
        # Solute row picked the 95% stock and computed dilution
        solute_row = next(r for r in suggestion.rows if r.role == "solute")
        assert solute_row.suggested_lot_id == stock_etoh.id
        # 50/95 ≈ 0.5263
        assert abs(solute_row.suggested_quantity - 0.526315789) < 1e-3
        # Solvent gets the remainder
        solvent_row = next(r for r in suggestion.rows if r.role == "solvent")
        assert abs(solvent_row.suggested_quantity - (1.0 - 0.526315789)) < 1e-3
        # Stock info populated for the solute row, surfacing the source
        assert solute_row.stock_info is not None
        assert solute_row.stock_info.concentration == 95.0
        assert solute_row.stock_info.unit == "%v/v"
        assert "EtOH 95" in solute_row.stock_info.display_text


def test_suggest_dilution_reads_stock_from_lot_not_recipe(app):
    """The recipe's solute concentration is a hint; the lot wins.

    Scenario: target HCl 1N. The recipe says "solute HCl 6 N"
    (operator thought they'd dilute from a 6N stock). But the
    actually available lot is HCl 12N. The suggest must use 12N
    from the lot, not 6N from the recipe.
    """
    with app.app_context():
        g = Group(name="D", slug="d")
        db.session.add(g)
        db.session.flush()
        hcl = Substance(name="HCl", molecular_formula="HCl")
        h2o = Substance(name="Water", molecular_formula="H2O")
        db.session.add_all([hcl, h2o])
        db.session.flush()

        m_12 = Mixture(
            name="HCl 12N",
            kind="solution",
            primary_concentration=12.0,
            primary_concentration_unit="N",
        )
        m_12.components = [
            MixtureComponent(
                substance_id=hcl.id,
                role="solute",
                concentration=12.0,
                concentration_unit="N",
                position=0,
            ),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_12)
        db.session.flush()

        # Recipe hint says 6N (different from the actual lot's 12N).
        m_1 = Mixture(
            name="HCl 1N",
            kind="solution",
            primary_concentration=1.0,
            primary_concentration_unit="N",
        )
        m_1.components = [
            MixtureComponent(
                substance_id=hcl.id,
                role="solute",
                concentration=6.0,
                concentration_unit="N",
                position=0,
            ),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_1)
        db.session.flush()

        stock = InventoryItem(
            mixture_id=m_12.id,
            group_id=g.id,
            batch_code="HCL12N-001",
            quantity_mL=5000.0,
            initial_quantity_mL=5000.0,
            is_active=True,
        )
        water = InventoryItem(
            substance_id=h2o.id,
            group_id=g.id,
            batch_code="H2O-001",
            quantity_mL=20000.0,
            initial_quantity_mL=20000.0,
            is_active=True,
        )
        db.session.add_all([stock, water])
        db.session.commit()

        suggestion = suggest_consumptions(
            mixture=m_1,
            target_quantity=1,
            target_unit="L",
        )
        solute_row = next(r for r in suggestion.rows if r.role == "solute")
        # 1 L × 1 N / 12 N ≈ 83.33 mL solute → rendered as 0.0833 L
        # NOT 1 L × 1 / 6 ≈ 0.1667 (the wrong answer if we'd used
        # the recipe hint).
        assert abs(solute_row.suggested_quantity - (1.0 / 12.0)) < 1e-4
        assert solute_row.stock_info.concentration == 12.0


def test_suggest_dilution_compatible_unit_groups(app):
    """mM stock → M target works (both are molarity)."""
    with app.app_context():
        g = Group(name="M", slug="m")
        db.session.add(g)
        db.session.flush()
        s = Substance(name="NaCl")
        h2o = Substance(name="Water")
        db.session.add_all([s, h2o])
        db.session.flush()

        m_stock = Mixture(
            name="NaCl 1000 mM",
            kind="solution",
            primary_concentration=1000.0,
            primary_concentration_unit="mM",
        )
        m_stock.components = [
            MixtureComponent(
                substance_id=s.id,
                role="solute",
                concentration=1000.0,
                concentration_unit="mM",
                position=0,
            ),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_stock)
        db.session.flush()

        m_target = Mixture(
            name="NaCl 0.5 M",
            kind="solution",
            primary_concentration=0.5,
            primary_concentration_unit="M",
        )
        m_target.components = [
            MixtureComponent(substance_id=s.id, role="solute", position=0),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_target)
        db.session.flush()

        db.session.add(
            InventoryItem(
                mixture_id=m_stock.id,
                group_id=g.id,
                batch_code="NACL-1M",
                quantity_mL=2000.0,
                initial_quantity_mL=2000.0,
                is_active=True,
            )
        )
        db.session.add(
            InventoryItem(
                substance_id=h2o.id,
                group_id=g.id,
                quantity_mL=10000.0,
                initial_quantity_mL=10000.0,
                is_active=True,
            )
        )
        db.session.commit()

        suggestion = suggest_consumptions(
            mixture=m_target,
            target_quantity=1,
            target_unit="L",
        )
        solute_row = next(r for r in suggestion.rows if r.role == "solute")
        # 0.5 M / (1000 mM = 1 M) = 0.5 → 500 mL
        assert abs(solute_row.suggested_quantity - 0.5) < 1e-3


def test_suggest_dilution_incompatible_units_falls_back(app):
    """A %v/v stock can't dilute into an N target — fallback."""
    with app.app_context():
        g = Group(name="X", slug="x")
        db.session.add(g)
        db.session.flush()
        s = Substance(name="HCl")
        h2o = Substance(name="Water")
        db.session.add_all([s, h2o])
        db.session.flush()

        # Stock in %v/v
        m_stock = Mixture(
            name="HCl 37% v/v",
            kind="solution",
            primary_concentration=37.0,
            primary_concentration_unit="%v/v",
        )
        m_stock.components = [
            MixtureComponent(
                substance_id=s.id,
                role="solute",
                concentration=37.0,
                concentration_unit="%v/v",
                position=0,
            ),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_stock)
        db.session.flush()

        # Target in N
        m_target = Mixture(
            name="HCl 6N",
            kind="solution",
            primary_concentration=6.0,
            primary_concentration_unit="N",
        )
        m_target.components = [
            MixtureComponent(substance_id=s.id, role="solute", position=0),
            MixtureComponent(substance_id=h2o.id, role="solvent", position=1),
        ]
        db.session.add(m_target)
        db.session.flush()

        db.session.add(
            InventoryItem(
                mixture_id=m_stock.id,
                group_id=g.id,
                quantity_mL=2000.0,
                initial_quantity_mL=2000.0,
                is_active=True,
            )
        )
        db.session.add(
            InventoryItem(
                substance_id=h2o.id,
                group_id=g.id,
                quantity_mL=10000.0,
                initial_quantity_mL=10000.0,
                is_active=True,
            )
        )
        db.session.commit()

        suggestion = suggest_consumptions(
            mixture=m_target,
            target_quantity=1,
            target_unit="L",
        )

    # Must surface a warning about incompatible units
    assert any("incompatibili" in w.lower() or "unit" in w.lower() for w in suggestion.warnings)


# ── Derived expiry (Settimana 7 patch 14.6.8) ──────────────────────


def test_output_lot_expiry_derives_from_earliest_precursor(app):
    """When output_expiry_date is left blank, the output lot inherits
    the *earliest* expiry among the precursor lots. The produced
    mixture can't reasonably outlive its shortest-lived input.
    """
    from datetime import date

    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        # Give the precursor lots distinct expiry dates so we can
        # tell which one was picked.
        stock_hcl = db.session.get(InventoryItem, ctx["stock_hcl_id"])
        stock_water = db.session.get(InventoryItem, ctx["stock_water_id"])
        stock_hcl.expiry_date = date(2027, 12, 31)
        stock_water.expiry_date = date(2028, 6, 30)
        db.session.commit()

        inp = PrepInput(
            mixture_id=ctx["m_6n_id"],
            target_quantity=4.0,
            target_quantity_unit="L",
            consumptions=[
                ConsumptionInput(
                    inventory_item_id=ctx["stock_hcl_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["stock_water_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
            ],
            output_batch_code=None,
            output_location="Shelf A",
            output_expiry_date=None,  # ← blank
            output_notes=None,
            prepared_by_id=None,
        )
        prep = execute_preparation(inp)
        # Earliest of (2027-12-31, 2028-06-30) → 2027-12-31
        assert prep.output_lot.expiry_date == date(2027, 12, 31)


def test_explicit_output_expiry_overrides_derived_default(app):
    """If the operator passes output_expiry_date explicitly, the
    derived default is bypassed even when precursors have expiries."""
    from datetime import date

    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        stock_hcl = db.session.get(InventoryItem, ctx["stock_hcl_id"])
        stock_hcl.expiry_date = date(2027, 1, 1)
        db.session.commit()

        inp = PrepInput(
            mixture_id=ctx["m_6n_id"],
            target_quantity=4.0,
            target_quantity_unit="L",
            consumptions=[
                ConsumptionInput(
                    inventory_item_id=ctx["stock_hcl_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["stock_water_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
            ],
            output_batch_code=None,
            output_location="Shelf A",
            output_expiry_date="2030-06-15",  # ← explicit
            output_notes=None,
            prepared_by_id=None,
        )
        prep = execute_preparation(inp)
        assert prep.output_lot.expiry_date == date(2030, 6, 15)


def test_output_expiry_left_blank_when_no_precursor_has_one(app):
    """If none of the precursors have an expiry_date, the output
    lot has no expiry either — we don't invent one."""
    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        # Leave precursor expiry_date as None (the default)
        inp = PrepInput(
            mixture_id=ctx["m_6n_id"],
            target_quantity=4.0,
            target_quantity_unit="L",
            consumptions=[
                ConsumptionInput(
                    inventory_item_id=ctx["stock_hcl_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["stock_water_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
            ],
            output_batch_code=None,
            output_location="Shelf A",
            output_expiry_date=None,
            output_notes=None,
            prepared_by_id=None,
        )
        prep = execute_preparation(inp)
        assert prep.output_lot.expiry_date is None


# ── Cost imputation (Settimana 7 patch 14.6.8) ─────────────────────


def test_prep_total_cost_sums_consumed_lot_costs(app):
    """Prep cost = sum of (cost_per_unit * consumed quantity) for
    each precursor lot."""
    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        stock_hcl = db.session.get(InventoryItem, ctx["stock_hcl_id"])
        stock_water = db.session.get(InventoryItem, ctx["stock_water_id"])
        # 5000 mL @ 100 € → 0.02 €/mL
        stock_hcl.total_cost_eur = 100.0
        # 20000 mL @ 10 € → 0.0005 €/mL
        stock_water.total_cost_eur = 10.0
        db.session.commit()

        inp = PrepInput(
            mixture_id=ctx["m_6n_id"],
            target_quantity=4.0,
            target_quantity_unit="L",
            consumptions=[
                ConsumptionInput(
                    inventory_item_id=ctx["stock_hcl_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["stock_water_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
            ],
            output_batch_code=None,
            output_location="Shelf A",
            output_expiry_date=None,
            output_notes=None,
            prepared_by_id=None,
        )
        prep = execute_preparation(inp)
        # HCl: 2000 mL * 0.02 = 40 €
        # H2O: 2000 mL * 0.0005 = 1 €
        # Total: 41 €
        assert prep.total_cost_eur == 41.0
        # Per unit: 41 / 4000 mL = 0.01025 €/mL
        assert abs(prep.cost_per_unit - 0.01025) < 1e-6


def test_prep_total_cost_none_when_any_lot_missing_cost(app):
    """If even one consumed lot is missing cost data, total_cost is
    None (not 0) — under-reporting silently is worse than admitting
    ignorance."""
    with app.app_context():
        ctx = _setup_hcl_dilution_lab()
        stock_hcl = db.session.get(InventoryItem, ctx["stock_hcl_id"])
        stock_hcl.total_cost_eur = 100.0
        # stock_water has no cost
        db.session.commit()

        inp = PrepInput(
            mixture_id=ctx["m_6n_id"],
            target_quantity=4.0,
            target_quantity_unit="L",
            consumptions=[
                ConsumptionInput(
                    inventory_item_id=ctx["stock_hcl_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
                ConsumptionInput(
                    inventory_item_id=ctx["stock_water_id"],
                    quantity_consumed=2.0,
                    quantity_unit="L",
                ),
            ],
            output_batch_code=None,
            output_location="Shelf A",
            output_expiry_date=None,
            output_notes=None,
            prepared_by_id=None,
        )
        prep = execute_preparation(inp)
        assert prep.total_cost_eur is None


def test_consumption_imputed_cost_kg_to_g_normalisation(app):
    """Consuming in kg from a lot priced per g should normalise."""
    with app.app_context():
        from stoic_eln.models.mixture_prep import MixturePrepConsumption

        ctx = _setup_hcl_dilution_lab()
        # Make a mass-based lot manually for this test
        from stoic_eln.models.substance import Substance

        sub = Substance(name="NaOH solid")
        db.session.add(sub)
        db.session.flush()
        from stoic_eln.models.inventory import InventoryItem as IItem

        lot = IItem(
            substance_id=sub.id,
            group_id=1,
            batch_code="NAOH-001",
            quantity_g=1000.0,
            initial_quantity_g=1000.0,
            total_cost_eur=50.0,  # → 0.05 €/g
            is_active=True,
        )
        db.session.add(lot)
        db.session.commit()

        # Build a consumption manually (don't run a full prep — we
        # just want the cost math)
        from stoic_eln.models.mixture_prep import MixturePrep

        prep = MixturePrep(
            code="X",
            year=2026,
            mixture_id=ctx["m_6n_id"],
            target_quantity=1.0,
            target_quantity_unit="L",
        )
        db.session.add(prep)
        db.session.flush()
        cons = MixturePrepConsumption(
            prep_id=prep.id,
            inventory_item_id=lot.id,
            quantity_consumed=0.5,
            quantity_unit="kg",  # = 500 g
            position=0,
        )
        db.session.add(cons)
        db.session.commit()
        # 500 g * 0.05 €/g = 25 €
        assert cons.imputed_cost_eur == 25.0
