"""Tests for the SMILES → SVG renderer (patch 14.6.4)."""

from __future__ import annotations

import pytest

from stoic_eln.services.scheme_image import render_molecule_svg


# ── Happy path ───────────────────────────────────────────────────


def test_renders_ethanol_to_svg():
    """Trivial 2-atom molecule round-trips through RDKit."""
    svg = render_molecule_svg("CCO")
    assert svg is not None
    assert svg.startswith("<svg")
    assert "</svg>" in svg


def test_renders_caffeine_to_svg():
    """Multi-ring molecule with heteroatoms. Output should be
    substantially larger than ethanol due to more atoms/bonds."""
    svg_ethanol = render_molecule_svg("CCO")
    svg_caffeine = render_molecule_svg("CN1C=NC2=C1C(=O)N(C(=O)N2C)C")
    assert svg_caffeine is not None
    assert len(svg_caffeine) > len(svg_ethanol)


def test_returned_svg_has_no_xml_prolog():
    """We strip the XML prolog because we embed inline, not
    serve as a standalone document. Embedded XML prologs cause
    rendering quirks in some browsers."""
    svg = render_molecule_svg("CCO")
    assert not svg.startswith("<?xml")


def test_respects_width_and_height_options():
    """The width/height arguments should appear in the SVG
    viewBox or width/height attributes."""
    svg = render_molecule_svg("CCO", width_px=400, height_px=300)
    # RDKit emits width="400px" height="300px" or similar
    assert "400" in svg[:300]  # Should be in the opening svg tag
    assert "300" in svg[:300]


# ── Error handling ───────────────────────────────────────────────


def test_returns_none_for_empty_smiles():
    assert render_molecule_svg("") is None


def test_returns_none_for_invalid_smiles():
    """Garbage input shouldn't crash — just return None so the
    template can show a placeholder."""
    assert render_molecule_svg("XYZ_NOT_A_SMILES_") is None


def test_returns_none_for_reaction_smiles():
    """Reaction SMILES (with > separator) is not supported by
    this single-molecule renderer. Caller should use
    render_reaction_png instead."""
    assert render_molecule_svg("CC>>CO") is None
    assert render_molecule_svg("A>B>C") is None


def test_returns_none_for_none_input():
    """Handles None gracefully (no AttributeError)."""
    assert render_molecule_svg(None) is None


# ── Theme support ────────────────────────────────────────────────


def test_render_molecule_svg_light_default():
    """Default theme is 'light' (preserves backward compat with
    existing callers from patch 14.6.4)."""
    svg = render_molecule_svg("CCO")
    assert svg is not None


def test_render_molecule_svg_dark_returns_svg():
    """Dark theme renders too — just with different palette."""
    svg = render_molecule_svg("CCO", theme="dark")
    assert svg is not None
    assert "<svg" in svg


def test_dark_and_light_svgs_differ():
    """The dark and light SVGs for the same molecule should
    produce different output (different atom palettes)."""
    light = render_molecule_svg("CCN", theme="light")
    dark = render_molecule_svg("CCN", theme="dark")
    assert light != dark


def test_render_handles_unknown_theme_gracefully():
    """An unknown theme name should not crash — falls back to
    default behaviour (treated as light)."""
    svg = render_molecule_svg("CCO", theme="something-weird")
    assert svg is not None
