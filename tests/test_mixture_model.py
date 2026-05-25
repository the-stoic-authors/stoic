"""Tests for the Mixture and MixtureComponent models (patch 13.0).

These exercise the data shape: model construction, the XOR constraint
on InventoryItem, the derived/effective GHS properties, and the
display label.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from stoic_eln.extensions import db
from stoic_eln.models import (
    Group,
    InventoryItem,
    Mixture,
    MixtureComponent,
    Substance,
)
from stoic_eln.models.mixture import (
    COMPONENT_ROLE_SOLUTE,
    COMPONENT_ROLE_SOLVENT,
    MIXTURE_KIND_ELUENT,
    MIXTURE_KIND_SOLUTION,
)


# ── Helpers ────────────────────────────────────────────────────────


def _make_group(label: str = "L") -> Group:
    """Create and persist a minimal group for FK targets."""
    g = Group(name=label, slug=label.lower())
    db.session.add(g)
    db.session.flush()
    return g


def _make_substance(name: str, **kwargs) -> Substance:
    """Create and persist a minimal substance."""
    s = Substance(name=name, **kwargs)
    db.session.add(s)
    db.session.flush()
    return s


# ── Mixture: basic creation ────────────────────────────────────────


def test_mixture_quick_label_no_components(app):
    """Quick-label use case: mixture with name + concentration but no
    components. Should persist and round-trip cleanly.
    """
    with app.app_context():
        m = Mixture(
            name="HCl 1N",
            kind=MIXTURE_KIND_SOLUTION,
            primary_concentration=1.0,
            primary_concentration_unit="N",
        )
        db.session.add(m)
        db.session.commit()
        mid = m.id

    with app.app_context():
        m2 = db.session.get(Mixture, mid)
        assert m2.name == "HCl 1N"
        assert m2.primary_concentration == 1.0
        assert m2.primary_concentration_unit == "N"
        assert m2.components == []
        assert m2.display_label == "HCl 1N (1 N)"


def test_mixture_with_components(app):
    """Detailed mixture: HCl + water with concentrations specified."""
    with app.app_context():
        hcl = _make_substance("Hydrogen chloride", molecular_formula="HCl")
        water = _make_substance("Water", molecular_formula="H2O")
        m = Mixture(
            name="HCl 1N",
            kind=MIXTURE_KIND_SOLUTION,
            primary_concentration=1.0,
            primary_concentration_unit="N",
        )
        m.components = [
            MixtureComponent(
                substance_id=hcl.id,
                role=COMPONENT_ROLE_SOLUTE,
                concentration=1.0,
                concentration_unit="N",
                position=0,
            ),
            MixtureComponent(
                substance_id=water.id,
                role=COMPONENT_ROLE_SOLVENT,
                position=1,
            ),
        ]
        db.session.add(m)
        db.session.commit()
        mid = m.id

    with app.app_context():
        m2 = db.session.get(Mixture, mid)
        assert len(m2.components) == 2
        # Ordered by position
        assert m2.components[0].role == COMPONENT_ROLE_SOLUTE
        assert m2.components[1].role == COMPONENT_ROLE_SOLVENT
        assert m2.components[0].substance.name == "Hydrogen chloride"


def test_mixture_eluent_with_two_cosolvents(app):
    """Chromatography eluent: two cosolvents with %v/v concentrations."""
    with app.app_context():
        hex_ = _make_substance("Hexane", molecular_formula="C6H14")
        etoac = _make_substance("Ethyl acetate", molecular_formula="C4H8O2")
        m = Mixture(
            name="Eluent A 95:5 hexane:EtOAc",
            kind=MIXTURE_KIND_ELUENT,
        )
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
        db.session.commit()
        # No primary_concentration set → display_label is just the name
        assert m.display_label == "Eluent A 95:5 hexane:EtOAc"
        assert len(m.components) == 2


# ── GHS derivation ─────────────────────────────────────────────────


def test_mixture_derived_pictograms_unions_components(app):
    """Pictograms derive from the union of component substances."""
    with app.app_context():
        hcl = _make_substance(
            "HCl",
            ghs_pictograms=["GHS05", "GHS07"],
            h_phrases=["H314", "H335"],
        )
        water = _make_substance("Water", ghs_pictograms=[])
        m = Mixture(name="HCl 1N", kind=MIXTURE_KIND_SOLUTION)
        m.components = [
            MixtureComponent(substance_id=hcl.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(m)
        db.session.commit()

        assert m.derived_pictograms == ["GHS05", "GHS07"]
        assert m.derived_h_phrases == ["H314", "H335"]
        # No override set → effective view matches derived
        assert m.effective_pictograms == ["GHS05", "GHS07"]


def test_mixture_pictogram_override_takes_precedence(app):
    """When ``ghs_pictograms_override`` is set, it overrides the union.

    This is the dilute-solution case: NaOH 0.01M behaves like water,
    not like the pure substance, and the user can clear the inherited
    hazards.
    """
    with app.app_context():
        naoh = _make_substance(
            "NaOH",
            ghs_pictograms=["GHS05"],
            h_phrases=["H314"],
        )
        water = _make_substance("Water")
        m = Mixture(
            name="NaOH 0.01M",
            kind=MIXTURE_KIND_SOLUTION,
            primary_concentration=0.01,
            primary_concentration_unit="M",
            ghs_pictograms_override=[],  # explicitly clear
            h_phrases_override=[],
        )
        m.components = [
            MixtureComponent(substance_id=naoh.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(m)
        db.session.commit()

        # Derived shows the inherited hazards
        assert m.derived_pictograms == ["GHS05"]
        # Effective is the override (empty)
        assert m.effective_pictograms == []
        assert m.effective_h_phrases == []


def test_mixture_empty_override_is_distinct_from_no_override(app):
    """``[]`` and ``None`` are semantically different.

    ``None`` means "use derived"; ``[]`` means "explicitly cleared".
    The effective view must respect this.
    """
    with app.app_context():
        hcl = _make_substance("HCl", ghs_pictograms=["GHS05"])
        m = Mixture(name="m", kind="solution")
        m.components = [MixtureComponent(substance_id=hcl.id, role="solute")]
        db.session.add(m)
        db.session.commit()
        assert m.effective_pictograms == ["GHS05"]  # None → derived
        m.ghs_pictograms_override = []
        db.session.commit()
        assert m.effective_pictograms == []  # [] → cleared


# ── InventoryItem XOR constraint ────────────────────────────────────


def test_inventory_item_for_substance_only(app):
    """Lot of a pure substance — substance_id set, mixture_id NULL."""
    with app.app_context():
        g = _make_group()
        s = _make_substance("NaCl")
        it = InventoryItem(
            substance_id=s.id,
            group_id=g.id,
            batch_code="NACL-001",
            quantity_g=10,
            initial_quantity_g=10,
            is_active=True,
        )
        db.session.add(it)
        db.session.commit()
        assert it.kind == "substance"
        assert it.display_name == "NaCl"


def test_inventory_item_for_mixture_only(app):
    """Lot of a mixture — mixture_id set, substance_id NULL."""
    with app.app_context():
        g = _make_group("L2")
        m = Mixture(
            name="HCl 1N",
            kind="solution",
            primary_concentration=1.0,
            primary_concentration_unit="N",
        )
        db.session.add(m)
        db.session.flush()
        it = InventoryItem(
            mixture_id=m.id,
            group_id=g.id,
            batch_code="HCL-1N-001",
            quantity_mL=500,
            initial_quantity_mL=500,
            is_active=True,
        )
        db.session.add(it)
        db.session.commit()
        assert it.kind == "mixture"
        assert it.display_name == "HCl 1N (1 N)"
        assert it.mixture is not None
        assert it.substance is None


def test_inventory_item_rejects_neither_substance_nor_mixture(app):
    """A lot must reference SOMETHING. Both NULL → CHECK fails."""
    with app.app_context():
        g = _make_group("L3")
        it = InventoryItem(
            group_id=g.id,
            batch_code="ORPHAN",
            is_active=True,
            quantity_g=1,
            initial_quantity_g=1,
        )
        db.session.add(it)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_inventory_item_rejects_both_substance_and_mixture(app):
    """A lot can't be both. Both set → CHECK fails."""
    with app.app_context():
        g = _make_group("L4")
        s = _make_substance("X")
        m = Mixture(name="m", kind="solution")
        db.session.add(m)
        db.session.flush()
        it = InventoryItem(
            substance_id=s.id,
            mixture_id=m.id,
            group_id=g.id,
            is_active=True,
            quantity_g=1,
            initial_quantity_g=1,
        )
        db.session.add(it)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_mixture_can_have_multiple_lots(app):
    """The classic use case: HCl 1N stock has two bottles in stock,
    each its own lot with its own batch code and expiry."""
    with app.app_context():
        from datetime import date

        g = _make_group("L5")
        m = Mixture(
            name="HCl 1N",
            kind="solution",
            primary_concentration=1.0,
            primary_concentration_unit="N",
        )
        db.session.add(m)
        db.session.flush()
        for batch in ("HCL-1N-A", "HCL-1N-B"):
            db.session.add(
                InventoryItem(
                    mixture_id=m.id,
                    group_id=g.id,
                    batch_code=batch,
                    quantity_mL=500,
                    initial_quantity_mL=500,
                    is_active=True,
                    expiry_date=date(2027, 1, 1),
                )
            )
        db.session.commit()
        assert len(m.inventory_items) == 2
        assert {it.batch_code for it in m.inventory_items} == {
            "HCL-1N-A",
            "HCL-1N-B",
        }


def test_substance_uniqueness_unaffected_by_mixtures(app):
    """The classic Substance.inchi_key uniqueness constraint must
    still hold after adding mixtures — you still can't create two
    HCl rows in the substance catalogue. Mixtures bypass the issue
    by having their own table.
    """
    with app.app_context():
        s1 = _make_substance("HCl", inchi_key="VEXZGXHMUGYJMC-UHFFFAOYSA-N")
        # Now create three different mixtures of HCl at different
        # concentrations — none of them adds to the substance table.
        for normality in (1, 6, 12):
            m = Mixture(
                name=f"HCl {normality}N",
                kind="solution",
                primary_concentration=float(normality),
                primary_concentration_unit="N",
            )
            m.components = [
                MixtureComponent(
                    substance_id=s1.id,
                    role="solute",
                    concentration=float(normality),
                    concentration_unit="N",
                )
            ]
            db.session.add(m)
        db.session.commit()
        # Substance table still has exactly 1 HCl row.
        rows = Substance.query.filter_by(name="HCl").all()
        assert len(rows) == 1
        # Mixture table has 3 distinct rows.
        mix_rows = Mixture.query.filter(Mixture.name.like("HCl %")).all()
        assert len(mix_rows) == 3


# ── Display label ───────────────────────────────────────────────────


def test_mixture_display_label_with_concentration(app):
    """``display_label`` formats concentration and unit when set."""
    with app.app_context():
        m = Mixture(
            name="HCl",
            kind="solution",
            primary_concentration=12.0,
            primary_concentration_unit="N",
        )
        assert m.display_label == "HCl (12 N)"


def test_mixture_display_label_without_concentration(app):
    """No concentration → just the name."""
    with app.app_context():
        m = Mixture(name="Eluent A", kind="eluent")
        assert m.display_label == "Eluent A"


# ── Mixture as component (Settimana 7 patch 14.6.7) ────────────────


def test_mixture_can_have_another_mixture_as_component(app):
    """The classic use case: HCl 6N prepared from HCl 12N stock.

    HCl 12N has substance components (HCl, water); HCl 6N has
    HCl 12N itself as a single 'solute-equivalent' component.
    """
    with app.app_context():
        hcl = _make_substance(
            "HCl",
            ghs_pictograms=["GHS05", "GHS07"],
            h_phrases=["H314"],
        )
        water = _make_substance("Water", ghs_pictograms=[])

        # HCl 12N from gas + water (manual lot)
        hcl12 = Mixture(
            name="HCl 12N",
            kind=MIXTURE_KIND_SOLUTION,
            primary_concentration=12.0,
            primary_concentration_unit="N",
        )
        hcl12.components = [
            MixtureComponent(substance_id=hcl.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(hcl12)
        db.session.commit()

        # HCl 6N diluted from HCl 12N
        hcl6 = Mixture(
            name="HCl 6N",
            kind=MIXTURE_KIND_SOLUTION,
            primary_concentration=6.0,
            primary_concentration_unit="N",
        )
        hcl6.components = [
            MixtureComponent(child_mixture_id=hcl12.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(hcl6)
        db.session.commit()

        # Round-trip
        db.session.expire_all()
        reloaded = db.session.get(Mixture, hcl6.id)
        assert len(reloaded.components) == 2
        # Find the mixture component
        mix_comp = next(
            (c for c in reloaded.components if c.is_mixture_component),
            None,
        )
        assert mix_comp is not None
        assert mix_comp.child_mixture.name == "HCl 12N"
        assert mix_comp.substance_id is None
        assert mix_comp.role == "solute"


def test_derived_pictograms_recurse_into_child_mixture(app):
    """Hazards from the inner mixture propagate up to the outer.

    HCl 6N inherits GHS05 + GHS07 from HCl 12N (which got them
    from the HCl substance). Verifies the recursive derivation.
    """
    with app.app_context():
        hcl = _make_substance(
            "HCl",
            ghs_pictograms=["GHS05", "GHS07"],
            h_phrases=["H314"],
        )
        water = _make_substance("Water", ghs_pictograms=[])

        hcl12 = Mixture(name="HCl 12N", kind=MIXTURE_KIND_SOLUTION)
        hcl12.components = [
            MixtureComponent(substance_id=hcl.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(hcl12)
        db.session.commit()

        hcl6 = Mixture(name="HCl 6N", kind=MIXTURE_KIND_SOLUTION)
        hcl6.components = [
            MixtureComponent(child_mixture_id=hcl12.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(hcl6)
        db.session.commit()

        # Pictograms come from HCl through HCl 12N
        assert hcl6.derived_pictograms == ["GHS05", "GHS07"]
        # H-phrases too
        assert hcl6.derived_h_phrases == ["H314"]


def test_child_mixture_override_blocks_further_recursion(app):
    """If the inner mixture has a pictogram override, the outer
    uses the override (not the inner's own derived list).

    HCl 12N overrides to just GHS05 → HCl 6N also sees just GHS05,
    even though the bare HCl substance would also contribute GHS07.
    """
    with app.app_context():
        hcl = _make_substance(
            "HCl",
            ghs_pictograms=["GHS05", "GHS07"],
        )
        water = _make_substance("Water", ghs_pictograms=[])

        hcl12 = Mixture(
            name="HCl 12N",
            kind=MIXTURE_KIND_SOLUTION,
            # explicit override on the inner mixture
            ghs_pictograms_override=["GHS05"],
        )
        hcl12.components = [
            MixtureComponent(substance_id=hcl.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(hcl12)
        db.session.commit()

        hcl6 = Mixture(name="HCl 6N", kind=MIXTURE_KIND_SOLUTION)
        hcl6.components = [
            MixtureComponent(child_mixture_id=hcl12.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(hcl6)
        db.session.commit()

        # Only GHS05 — the override on hcl12 short-circuits
        # recursion into the bare HCl substance.
        assert hcl6.derived_pictograms == ["GHS05"]


def test_derived_pictograms_handles_cycle_gracefully(app):
    """A pathological cycle (A → B → A) must not infinite-loop.

    The visited-set guard in ``_derived_pictograms_recursive``
    catches it and returns an empty/finite result rather than
    blowing the stack.
    """
    with app.app_context():
        hcl = _make_substance("HCl", ghs_pictograms=["GHS05"])
        water = _make_substance("Water", ghs_pictograms=[])

        m_a = Mixture(name="A", kind=MIXTURE_KIND_SOLUTION)
        m_a.components = [MixtureComponent(substance_id=hcl.id, role="solute")]
        db.session.add(m_a)

        m_b = Mixture(name="B", kind=MIXTURE_KIND_SOLUTION)
        m_b.components = [MixtureComponent(substance_id=water.id, role="solute")]
        db.session.add(m_b)
        db.session.commit()

        # Now create the cycle: A contains B, B contains A.
        # (User-error scenario; the UI prevents this, but the
        # schema doesn't, so the cycle guard has to.)
        m_a.components = [
            MixtureComponent(child_mixture_id=m_b.id, role="solute"),
        ]
        m_b.components = [
            MixtureComponent(child_mixture_id=m_a.id, role="solute"),
        ]
        db.session.commit()

        # Must terminate — the exact value matters less than the
        # fact we don't hang or blow the stack.
        result = m_a.derived_pictograms
        assert isinstance(result, list)


def test_mixture_component_is_mixture_component_helper(app):
    """The ``is_mixture_component`` property correctly distinguishes
    the two flavours of MixtureComponent."""
    with app.app_context():
        hcl = _make_substance("HCl")
        water = _make_substance("Water")

        stock = Mixture(name="Stock", kind=MIXTURE_KIND_SOLUTION)
        stock.components = [
            MixtureComponent(substance_id=hcl.id, role="solute"),
        ]
        db.session.add(stock)
        db.session.commit()

        diluted = Mixture(name="Diluted", kind=MIXTURE_KIND_SOLUTION)
        sub_comp = MixtureComponent(substance_id=water.id, role="solvent")
        mix_comp = MixtureComponent(child_mixture_id=stock.id, role="solute")
        diluted.components = [sub_comp, mix_comp]
        db.session.add(diluted)
        db.session.commit()

        assert sub_comp.is_mixture_component is False
        assert mix_comp.is_mixture_component is True
        assert sub_comp.display_name == "Water"
        assert mix_comp.display_name == stock.display_label


def test_suggested_expiry_date_min_across_components(app):
    """suggested_expiry_date returns the earliest expiry across all
    components' active lots."""
    from datetime import date

    with app.app_context():
        g = Group(name="L", slug="l")
        db.session.add(g)
        db.session.flush()
        hcl = _make_substance("HCl")
        water = _make_substance("Water")

        # Two lots of HCl with different expiries; only the
        # active one with the earliest expiry should win.
        from stoic_eln.models.inventory import InventoryItem

        hcl_lot_old = InventoryItem(
            substance_id=hcl.id,
            group_id=g.id,
            batch_code="HCL-OLD",
            quantity_g=10.0,
            initial_quantity_g=10.0,
            expiry_date=date(2026, 1, 1),
            is_active=False,  # inactive — should be skipped
        )
        hcl_lot_active = InventoryItem(
            substance_id=hcl.id,
            group_id=g.id,
            batch_code="HCL-ACTIVE",
            quantity_g=10.0,
            initial_quantity_g=10.0,
            expiry_date=date(2027, 12, 31),
            is_active=True,
        )
        water_lot = InventoryItem(
            substance_id=water.id,
            group_id=g.id,
            batch_code="H2O-001",
            quantity_g=10.0,
            initial_quantity_g=10.0,
            expiry_date=date(2028, 6, 30),
            is_active=True,
        )
        db.session.add_all([hcl_lot_old, hcl_lot_active, water_lot])
        db.session.flush()

        m = Mixture(name="HCl 12N", kind=MIXTURE_KIND_SOLUTION)
        m.components = [
            MixtureComponent(substance_id=hcl.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(m)
        db.session.commit()

        # Min of (HCl active = 2027-12-31, Water = 2028-06-30) → 2027-12-31
        # The 2026-01-01 inactive lot is ignored.
        assert m.suggested_expiry_date() == date(2027, 12, 31)


def test_suggested_expiry_date_returns_none_without_lots(app):
    """When no component has an active lot with expiry, returns None
    (the form stays blank — we don't invent a date)."""
    with app.app_context():
        hcl = _make_substance("HCl")
        m = Mixture(name="HCl 12N", kind=MIXTURE_KIND_SOLUTION)
        m.components = [MixtureComponent(substance_id=hcl.id, role="solute")]
        db.session.add(m)
        db.session.commit()
        assert m.suggested_expiry_date() is None


def test_suggested_expiry_date_recurses_into_child_mixture(app):
    """A mixture component pointing at a child mixture: recurse and
    pick the earliest expiry from the child's components."""
    from datetime import date

    with app.app_context():
        g = Group(name="L", slug="l")
        db.session.add(g)
        db.session.flush()
        hcl = _make_substance("HCl")
        water = _make_substance("Water")

        from stoic_eln.models.inventory import InventoryItem

        hcl_lot = InventoryItem(
            substance_id=hcl.id,
            group_id=g.id,
            batch_code="HCL-ACT",
            quantity_g=10.0,
            initial_quantity_g=10.0,
            expiry_date=date(2027, 6, 30),
            is_active=True,
        )
        water_lot = InventoryItem(
            substance_id=water.id,
            group_id=g.id,
            batch_code="H2O-ACT",
            quantity_g=10.0,
            initial_quantity_g=10.0,
            expiry_date=date(2029, 12, 31),
            is_active=True,
        )
        db.session.add_all([hcl_lot, water_lot])
        db.session.flush()

        # HCl 12N: HCl (2027-06-30) + Water (2029-12-31) → suggested 2027-06-30
        hcl12 = Mixture(name="HCl 12N", kind=MIXTURE_KIND_SOLUTION)
        hcl12.components = [
            MixtureComponent(substance_id=hcl.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(hcl12)
        db.session.commit()

        # HCl 6N: HCl 12N (suggested 2027-06-30) + Water (2029-12-31) → 2027-06-30
        hcl6 = Mixture(name="HCl 6N", kind=MIXTURE_KIND_SOLUTION)
        hcl6.components = [
            MixtureComponent(child_mixture_id=hcl12.id, role="solute"),
            MixtureComponent(substance_id=water.id, role="solvent"),
        ]
        db.session.add(hcl6)
        db.session.commit()

        assert hcl6.suggested_expiry_date() == date(2027, 6, 30)
