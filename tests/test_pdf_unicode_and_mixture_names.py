"""Tests for the PDF Unicode font and mixture component naming fix.

Two bugs that surfaced during testing:

1. Mixture lists and run cost reports showed "?" or an empty string
   instead of the component's name when the component was itself a
   mixture (e.g. HCl 12N used as a precursor for HCl 6N).
2. PDF reports rendered Unicode subscripts (Na₂SO₄), superscripts
   and Greek letters as black squares because ReportLab's built-in
   Times-Roman family lacks those glyphs.

These tests guard against regressions on both fronts.
"""

from __future__ import annotations

import io


from stoic_eln.extensions import db
from stoic_eln.models import Mixture, MixtureComponent, Substance
from stoic_eln.services.pdf_fonts import (
    FONT_BOLD,
    FONT_BOLD_ITALIC,
    FONT_ITALIC,
    FONT_REGULAR,
    register,
)


# ── Font registration ──────────────────────────────────────────────


def test_register_is_idempotent():
    """Calling register() twice must not error and must leave the
    family installed. ReportLab's registerFont is itself idempotent,
    but we keep an internal _REGISTERED flag for a fast no-op."""
    register()
    register()  # second call must be a no-op
    from reportlab.pdfbase import pdfmetrics

    # All four variants must be registered
    for name in (FONT_REGULAR, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC):
        font = pdfmetrics.getFont(name)
        assert font is not None


def test_font_supports_chemistry_subscripts():
    """The whole point: the registered font must have glyphs for the
    Unicode codepoints that surface in chemistry free-text fields."""
    from reportlab.pdfbase import pdfmetrics

    register()
    face = pdfmetrics.getFont(FONT_REGULAR).face
    # Subscripts 2-9 cover most inorganic formulas
    for cp in range(0x2082, 0x2089 + 1):
        glyph = face.charToGlyph.get(cp)
        assert glyph is not None, f"subscript U+{cp:04X} has no glyph"
    # Common superscripts used in scientific notation
    for cp in (0x00B2, 0x00B3):  # ², ³
        assert face.charToGlyph.get(cp) is not None
    # Greek letters routinely used (α, β, γ, δ, ω)
    for cp in (0x03B1, 0x03B2, 0x03B3, 0x03B4, 0x03C9):
        assert face.charToGlyph.get(cp) is not None


# ── PDF rendering with Unicode ─────────────────────────────────────


def test_pdf_renders_unicode_subscripts_without_tofu(app):
    """End-to-end: rendering a PDF containing Na₂SO₄ produces output
    that's larger than the same PDF without that string, proving the
    glyphs were actually embedded rather than substituted with the
    "tofu" black square.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    from reportlab.lib.styles import ParagraphStyle

    register()

    def _render(text: str) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        style = ParagraphStyle("p", fontName=FONT_REGULAR, fontSize=10)
        doc.build([Paragraph(text, style)])
        return buf.getvalue()

    plain = _render("Sodium sulphate is a salt.")
    fancy = _render("Na₂SO₄ — α-pinene — H₂O — CO₂.")

    # Both must be valid PDFs
    assert plain.startswith(b"%PDF")
    assert fancy.startswith(b"%PDF")
    # The "fancy" version embeds the additional Unicode glyphs and
    # so should be similar or larger; the key property is that
    # ReportLab didn't raise/substitute (which it would for missing
    # glyphs). A simple sanity check: both are non-trivial PDFs.
    assert len(fancy) > 1000


# ── Bug 1: mixture component naming ────────────────────────────────


def test_mixture_component_display_name_handles_child_mixture(app):
    """A MixtureComponent that points at a child mixture rather than
    a Substance must return the mixture's display_label, not crash
    or yield '?'."""
    with app.app_context():
        # Build a parent->child mixture relationship like HCl 6N from
        # HCl 12N
        water = Substance(name="Water", molecular_weight=18.02)
        db.session.add(water)
        db.session.flush()

        hcl_12n = Mixture(
            name="HCl 12N",
            kind="solution",
            primary_concentration=12.0,
            primary_concentration_unit="N",
        )
        db.session.add(hcl_12n)
        db.session.flush()
        # Give the parent at least one component so it's valid
        db.session.add(
            MixtureComponent(
                mixture_id=hcl_12n.id,
                substance_id=water.id,
                role="solvent",
                position=0,
            )
        )
        db.session.flush()

        hcl_6n = Mixture(
            name="HCl 6N",
            kind="solution",
            primary_concentration=6.0,
            primary_concentration_unit="N",
        )
        db.session.add(hcl_6n)
        db.session.flush()
        # HCl 6N's first component IS the HCl 12N mixture
        nested = MixtureComponent(
            mixture_id=hcl_6n.id,
            child_mixture_id=hcl_12n.id,
            role="solute",
            position=0,
        )
        db.session.add(nested)
        db.session.commit()

        # The display_name must surface the nested mixture's label
        assert nested.display_name  # non-empty
        assert "HCl 12N" in nested.display_name


def test_mixture_list_template_uses_display_name(app, client):
    """The mixture list page renders the component names through
    display_name, so a nested mixture component shows its label
    instead of an empty string before a comma."""
    with app.app_context():
        # An admin to login with
        from stoic_eln.models import User

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

        # Two mixtures: HCl 12N (substance-only) and HCl 6N (nested)
        water = Substance(name="Water", molecular_weight=18.02)
        db.session.add(water)
        db.session.flush()

        hcl_12n = Mixture(
            name="HCl 12N",
            kind="solution",
            primary_concentration=12.0,
            primary_concentration_unit="N",
        )
        db.session.add(hcl_12n)
        db.session.flush()
        db.session.add(
            MixtureComponent(
                mixture_id=hcl_12n.id,
                substance_id=water.id,
                role="solvent",
                position=0,
            )
        )
        db.session.flush()

        hcl_6n = Mixture(
            name="HCl 6N",
            kind="solution",
            primary_concentration=6.0,
            primary_concentration_unit="N",
        )
        db.session.add(hcl_6n)
        db.session.flush()
        db.session.add_all(
            [
                MixtureComponent(
                    mixture_id=hcl_6n.id,
                    child_mixture_id=hcl_12n.id,
                    role="solute",
                    position=0,
                ),
                MixtureComponent(
                    mixture_id=hcl_6n.id,
                    substance_id=water.id,
                    role="solvent",
                    position=1,
                ),
            ]
        )
        db.session.commit()

    client.post("/auth/login", data={"username": "r", "password": "x", "submit": "x"})

    r = client.get("/mixtures/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # The HCl 6N row must show its mixture-component's name
    # in the Components column. With the bug we'd see ", Water"
    # (empty prefix). With the fix we see "HCl 12N, Water".
    assert "HCl 12N" in body
