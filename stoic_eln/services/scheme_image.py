"""Stoic ELN — Reaction scheme image generator (Settimana 5).

Renders a chemical reaction scheme (e.g. 'A.B>C>D') as a PNG image
using RDKit. Used to embed the scheme in PDF reports.

RDKit is an optional dependency: when it's not available, this module
returns ``None`` and the caller (PDF generator) falls back to plain
SMILES text. This keeps the test suite and minimal installs working
even without the heavy chemistry stack.
"""

from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# Cap to keep large schemes from consuming silly amounts of RAM.
_MAX_PIXEL_WIDTH = 2400
_DEFAULT_SUB_IMG = (380, 240)  # per-molecule cell


def render_reaction_png(
    smiles: str,
    *,
    target_width_px: int = 1400,
) -> bytes | None:
    """Render a reaction-SMILES (with '>') as a PNG image.

    Args:
        smiles: a SMILES string. Two flavours are accepted:
            - reaction SMILES with '>>' or 'A>B>C' (preferred)
            - dot-separated molecule SMILES — rendered as a row of
              molecules with '+' between them
        target_width_px: target width of the output image. RDKit
            auto-scales each molecule cell to fit. Capped at 2400 px.

    Returns:
        PNG bytes, or None if rendering failed (or RDKit missing).
    """
    if not smiles:
        return None

    target_width_px = min(int(target_width_px), _MAX_PIXEL_WIDTH)

    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, Draw
    except Exception as exc:  # noqa: BLE001
        logger.info("RDKit not available, skipping scheme image: %s", exc)
        return None

    try:
        if ">" in smiles:
            # Reaction SMILES — render with arrow.
            rxn = AllChem.ReactionFromSmarts(smiles, useSmiles=True)
            if rxn is None:
                return None
            n_mols = rxn.GetNumReactantTemplates() + rxn.GetNumProductTemplates()
            if n_mols == 0:
                return None
            cell_w = max(220, min(_DEFAULT_SUB_IMG[0],
                                  target_width_px // max(n_mols, 1)))
            cell_h = int(cell_w * 0.65)
            img = Draw.ReactionToImage(
                rxn,
                subImgSize=(cell_w, cell_h),
                useSVG=False,
            )
        else:
            # Plain molecule(s) — render side by side.
            parts = [s for s in smiles.split(".") if s]
            mols = [Chem.MolFromSmiles(p) for p in parts]
            mols = [m for m in mols if m is not None]
            if not mols:
                return None
            cell_w = max(220, min(_DEFAULT_SUB_IMG[0],
                                  target_width_px // max(len(mols), 1)))
            cell_h = int(cell_w * 0.85)
            img = Draw.MolsToGridImage(
                mols,
                molsPerRow=len(mols),
                subImgSize=(cell_w, cell_h),
                useSVG=False,
            )

        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        logger.exception("Failed to render reaction scheme: %s", smiles)
        return None


def render_molecule_svg(
    smiles: str,
    *,
    width_px: int = 320,
    height_px: int = 240,
    theme: str = "light",
) -> str | None:
    """Render a single-molecule SMILES as an inline SVG string.

    Used for the PubChem import preview (Settimana 7 patch 14.6.4)
    where we want a scalable, crisp depiction of the molecule next
    to its identification metadata. SVG over PNG because:
      - sharp at any zoom level (matters on hi-DPI screens)
      - smaller payload for line-art molecules
      - we can theme it (light/dark) without re-rendering

    Args:
        smiles: a single-molecule SMILES (not a reaction SMILES).
            Reaction SMILES with ``>`` are rejected — use
            ``render_reaction_png`` for those.
        width_px, height_px: viewBox dimensions. RDKit auto-fits
            the molecule inside.
        theme: ``"light"`` (default) or ``"dark"``. In dark
            mode, bonds are drawn light-grey and atom labels in
            their dark-mode-friendly colours so the structure is
            readable on dark backgrounds.

    Returns:
        Inline SVG string (``<svg ...>...</svg>``), or None if
        rendering failed, RDKit is missing, or the SMILES is
        invalid.
    """
    if not smiles or ">" in smiles:
        return None

    try:
        from rdkit import Chem
        from rdkit.Chem import Draw
    except Exception:
        return None

    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        drawer = Draw.MolDraw2DSVG(width_px, height_px)
        opts = drawer.drawOptions()
        opts.padding = 0.05
        opts.clearBackground = False  # transparent SVG bg

        if theme == "dark":
            # In dark mode we draw bonds in a light grey, and atom
            # labels in a brighter version of their conventional
            # colours so they stay readable on a #1a1a1a-ish
            # background. Black-on-white defaults are unreadable.
            #
            # RDKit colours are RGB tuples in [0..1]. We start from
            # the default palette then overlay dark-friendly colours
            # for the atoms that typically appear (CHNO, halogens,
            # S, P). Carbon is the critical one — defaults to black,
            # we make it light grey so plain C atoms (rendered only
            # as bond endpoints) are visible.
            opts.setBackgroundColour((0, 0, 0, 0))  # fully transparent
            palette = {
                # atomic number -> (R, G, B)
                0:  (0.85, 0.85, 0.85),  # default / "unlabelled" atoms
                1:  (0.85, 0.85, 0.85),  # H
                6:  (0.85, 0.85, 0.85),  # C
                7:  (0.45, 0.55, 1.00),  # N — lighter blue
                8:  (1.00, 0.55, 0.55),  # O — lighter red
                9:  (0.50, 0.90, 0.50),  # F — lighter green
                15: (1.00, 0.65, 0.30),  # P — orange
                16: (1.00, 0.95, 0.40),  # S — yellow
                17: (0.50, 0.95, 0.55),  # Cl — green
                35: (0.85, 0.55, 0.40),  # Br — brown
                53: (0.75, 0.40, 0.85),  # I — purple
            }
            opts.updateAtomPalette(palette)
            # Bond lines (default is black). 0.85,0.85,0.85 = light grey
            try:
                opts.bondLineWidth = 1.5
            except Exception:
                pass

        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        svg = drawer.GetDrawingText()
        # RDKit emits an XML prolog (<?xml version="1.0"?>) that we
        # strip — we're embedding inline, not serving as a document.
        if svg.startswith("<?xml"):
            svg = svg.split("?>", 1)[-1].lstrip()
        return svg
    except Exception:
        logger.exception("Failed to render molecule SVG: %s", smiles)
        return None
