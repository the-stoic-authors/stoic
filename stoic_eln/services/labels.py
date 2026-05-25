"""Stoic — Labels service (Settimana 6 patch 12).

Generates printable PDF labels for inventory lots in three formats:

  * **Avery L7160** — A4 sheet, 24 labels (8 rows × 3 cols), 63.5 × 33.9 mm
  * **Avery L7164** — A4 sheet, 12 labels (6 rows × 2 cols), 63.5 × 72 mm
  * **Termica 62 mm** — single label per page, 62 × 40 mm (Brother QL / Dymo)

Each label shows: substance name + IUPAC name (italic), batch code,
expiry date, CAS, molecular formula, MW, density (when available),
GHS pictograms, H/P phrase codes, and a QR code containing JSON
metadata about the lot:

    {"lotto_id": 42, "batch": "AB-123",
     "sostanza": "Acetic acid", "scadenza": "2025-12-31"}

The larger Avery L7164 layout *also* embeds a 2D structural depiction
of the molecule (rendered by RDKit). Smaller formats (L7160, thermal)
omit it: the height budget is already razor-thin without giving up
~15 mm of label real estate.

Design notes
~~~~~~~~~~~~
* The QR is rendered with ReportLab's built-in :class:`QrCodeWidget` —
  no PIL/qrcode dependency, vector output preserved at any zoom.
* GHS pictograms are SVGs in ``static/img/ghs/`` rasterised once per
  process to PNG via ``svglib + reportlab.renderPM``. We embed them
  through ``canvas.drawImage`` rather than ``renderPDF.draw`` because
  the latter occasionally drops the vector content when combined with
  canvas-level transforms — easier to keep deterministic with a 600 dpi
  PNG, indistinguishable in print.
* The 2D molecule depiction is also a cached PNG, keyed by SMILES so
  several lots of the same substance reuse a single image.
* Layout is constraint-driven: the QR claims a fixed square in the
  top-right; the text block fills the left half; the GHS row + H/P
  codes drop to the bottom band; on the larger format, the structure
  goes between the text and the GHS band.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable

from flask import current_app
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing, Group
from reportlab.lib.colors import black, grey
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics

from stoic_eln.models.inventory import InventoryItem

log = logging.getLogger(__name__)


# ── Format definitions ─────────────────────────────────────────────


@dataclass(frozen=True)
class LabelFormat:
    """Geometry for one printable label format.

    Coordinates are in millimetres throughout this module; we multiply
    by ``mm`` (= 2.834...) at draw time to get ReportLab points.
    """

    key: str
    label: str  # human-readable name (translated at the route level)
    page_width_mm: float
    page_height_mm: float
    label_width_mm: float
    label_height_mm: float
    rows: int
    cols: int
    # Top-left corner of the first label, measured from the page top-left.
    margin_top_mm: float
    margin_left_mm: float
    # Gap between labels (rows go down, cols go right).
    gap_h_mm: float
    gap_v_mm: float

    @property
    def per_sheet(self) -> int:
        return self.rows * self.cols

    @property
    def is_sheet(self) -> bool:
        """True if this format prints multiple labels per page (Avery)."""
        return self.per_sheet > 1


# Avery L7160: 63.5 × 38.1 mm spec sheet, 24/page on A4 (8×3).
# Margin top: 15.1 mm, margin left: 7.2 mm, gap horiz: 2.5 mm, gap vert: 0.
# We use 33.9 mm as the safe printable height (3 mm bleed-free margin
# inside each label).
AVERY_L7160 = LabelFormat(
    key="avery_l7160",
    label="Avery L7160 (24/foglio, 63.5×33.9 mm)",
    page_width_mm=210.0,
    page_height_mm=297.0,
    label_width_mm=63.5,
    label_height_mm=33.9,
    rows=8,
    cols=3,
    margin_top_mm=15.1,
    margin_left_mm=7.2,
    gap_h_mm=2.5,
    gap_v_mm=0.0,
)

# Avery L7164: 63.5 × 72 mm, 12/page on A4 (6×2).
AVERY_L7164 = LabelFormat(
    key="avery_l7164",
    label="Avery L7164 (12/foglio, 63.5×72 mm)",
    page_width_mm=210.0,
    page_height_mm=297.0,
    label_width_mm=63.5,
    label_height_mm=72.0,
    rows=6,
    cols=2,
    margin_top_mm=8.5,
    margin_left_mm=14.5,
    gap_h_mm=4.0,
    gap_v_mm=0.0,
)

# Brother QL / Dymo continuous tape style. One label per "page".
# 62 mm width is the standard DK-22205/DK-44205 endless roll; 40 mm
# height is a comfortable cut for a chemistry lab lot.
THERMAL_62 = LabelFormat(
    key="thermal_62",
    label="Termica 62 mm (1/foglio, 62×40 mm)",
    page_width_mm=62.0,
    page_height_mm=40.0,
    label_width_mm=62.0,
    label_height_mm=40.0,
    rows=1,
    cols=1,
    margin_top_mm=0.0,
    margin_left_mm=0.0,
    gap_h_mm=0.0,
    gap_v_mm=0.0,
)

LABEL_FORMATS: dict[str, LabelFormat] = {
    AVERY_L7160.key: AVERY_L7160,
    AVERY_L7164.key: AVERY_L7164,
    THERMAL_62.key: THERMAL_62,
}


# ── QR payload ─────────────────────────────────────────────────────


def qr_payload(item: InventoryItem) -> str:
    """JSON payload encoded in the QR.

    Compact (no extra spaces), with stable key order so a fresh print
    of the same lot generates a bit-identical QR.
    """
    sub = item.substance
    mix = item.mixture
    return json.dumps(
        {
            "lotto_id": item.id,
            "batch": item.batch_code or "",
            "sostanza": (
                sub.name if sub
                else mix.display_label if mix
                else ""
            ),
            "scadenza": item.expiry_date.isoformat() if item.expiry_date else "",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _qr_drawing(payload: str, side_mm: float) -> Drawing:
    """Build a square ReportLab Drawing of the requested side length.

    The widget reports its native bounds in points; we scale uniformly
    to fit ``side_mm`` exactly. ``barLevel='M'`` tolerates ~15% damage
    which is plenty for printed labels.
    """
    w = QrCodeWidget(payload, barLevel="M")
    bounds = w.getBounds()
    native = bounds[2] - bounds[0]
    target = side_mm * mm
    scale = target / native if native else 1.0

    d = Drawing(target, target)
    g = Group(w)
    g.scale(scale, scale)
    g.translate(-bounds[0], -bounds[1])
    d.add(g)
    return d


# ── GHS pictograms (SVG → PNG, cached) ─────────────────────────────


# Cache stores raw PNG bytes keyed by GHS code. PNG (rather than the
# vector Drawing) because c.drawImage() composes reliably with the
# canvas's saveState/translate/scale, while renderPDF.draw() of an
# svglib-parsed Drawing sometimes drops the inner shapes when combined
# with canvas-level transforms — see svglib#249-style issues.
_ghs_cache: dict[str, bytes | None] = {}


# CSS custom properties used by the legacy hand-drawn pictograms; the
# official UN/UNECE SVGs use direct colour values (see ``_THEME_COLOR_MAP``
# below). svglib understands neither ``var(--name)`` nor a CSS class
# selector, so we resolve everything to literal RGB hex at load time.
_GHS_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "--ghs-bg": "#ffffff",
        "--ghs-border": "#e21d26",
        "--ghs-fg": "#000000",
    },
    "dark": {
        # Black background to match the dark UI theme; symbol inverts
        # to white. The red border stays red — the GHS standard
        # explicitly requires the red diamond regardless of background.
        "--ghs-bg": "#1a1a1a",
        "--ghs-border": "#e21d26",
        "--ghs-fg": "#ffffff",
    },
}


# Direct-colour theming for the official UN/UNECE SVGs.
#
# Those files write colours either as bare attributes (``fill="#fff"``,
# ``fill="red"``) or inside style declarations (``style="fill:#ffffff"``).
# We swap the canonical "white" and "black" tokens between themes while
# leaving the red diamond border untouched. The substitutions are
# applied as whole-token regex matches so a hex like ``#ff0000`` (red)
# is never mistaken for a leading ``#ff``.
#
# Order matters: substitute "white" before "black" using a sentinel
# placeholder, otherwise a naive sequential replace would turn black
# back into white on the second pass.
_THEME_COLOR_MAP: dict[str, list[tuple[str, str]]] = {
    "light": [],   # no-op
    "dark": [
        # white tokens -> sentinel
        (r"#ffffff\b", "__GHS_TMP_WHITE__"),
        (r"#fff\b",    "__GHS_TMP_WHITE__"),
        (r"\bwhite\b", "__GHS_TMP_WHITE__"),
        # black tokens -> white
        (r"#000000\b", "#ffffff"),
        (r"#000\b",    "#ffffff"),
        (r"\bblack\b", "#ffffff"),
        # sentinel -> dark bg
        (r"__GHS_TMP_WHITE__", "#1a1a1a"),
    ],
}


def _resolve_css_vars(svg_text: str, palette: dict[str, str]) -> str:
    """Substitute CSS ``var(--name, fallback)`` references in raw SVG.

    svglib parses the SVG without CSS-var resolution and emits a
    warning + drops the styled shape. We pre-process the file as a
    string. Pattern ``var(--name, fallback)`` is matched literally,
    name lookup is exact-match against ``palette``; if missing, the
    fallback in the SVG is used; if no fallback, an empty string is
    substituted (which svglib then treats as "no fill / no stroke",
    making the issue obvious in QA).

    No-op on SVGs that don't use ``var()`` (e.g. the official UN
    pictograms): the regex simply doesn't match.
    """
    import re

    pattern = re.compile(
        r"var\s*\(\s*(--[a-zA-Z0-9_-]+)\s*(?:,\s*([^)]+?))?\s*\)"
    )

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        fallback = (m.group(2) or "").strip()
        return palette.get(name, fallback)

    return pattern.sub(repl, svg_text)


def _apply_theme_colors(svg_text: str, theme: str) -> str:
    """Swap white/black colour tokens for the dark theme.

    Used on the official UN/UNECE pictograms which encode colours
    directly (``fill="#fff"``, ``style="fill:#000000"``, etc) rather
    than via CSS custom properties. The light theme is a no-op; the
    dark theme inverts white ↔ a near-black page colour, preserving
    the red border.

    Some of the official SVGs draw glyphs (e.g. the GHS02 flame) as
    paths *without* an explicit fill attribute, relying on the SVG
    default of ``fill="black"``. In dark mode we'd then end up drawing
    the symbol in black on top of the now-black diamond background —
    invisible. To compensate we inject ``fill="#ffffff"`` on every
    ``<path>`` that doesn't already carry a fill (attribute or inside
    a style declaration). Paths that DO have a fill went through the
    colour swap above and are already correct.
    """
    import re

    rules = _THEME_COLOR_MAP.get(theme, [])
    out = svg_text
    for pattern, replacement in rules:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)

    if theme == "dark":
        # Match a ``<path ...>`` element whose attributes contain
        # neither a ``fill="..."`` nor a ``style="…fill:…"`` clause.
        # The negative lookahead avoids touching paths that already
        # carry an explicit fill (which would turn red diamonds white).
        out = re.sub(
            r"<path(?![^>]*\bfill\s*=)(?![^>]*\bstyle\s*=\s*\"[^\"]*\bfill\s*:)"
            r"([^>]*)>",
            r'<path fill="#ffffff"\1>',
            out,
        )
    return out


def _ghs_png(code: str, *, theme: str = "light") -> bytes | None:
    """Load and rasterise a GHS pictogram. Returns PNG bytes or None.

    Cached per process keyed by ``(code, theme)`` — the same PNG is
    reused across all labels and pictograms in a single rendering pass
    (e.g. a full Avery sheet of the same substance gets the asset
    rasterised exactly once).

    ``theme`` controls colour substitution: ``"light"`` for the
    standard black-on-white GHS look (use this for printed labels and
    most contexts); ``"dark"`` for the dark UI variant where the
    diamond's interior matches a dark page background and the symbol
    inverts to white.
    """
    cache_key = f"{code}|{theme}"
    if cache_key in _ghs_cache:
        return _ghs_cache[cache_key]

    static = Path(current_app.root_path) / "static" / "img" / "ghs"

    # Fast path: pre-rendered PNG asset on disk.
    #
    # The official UN/UNECE pictograms ship as SVGs, but rasterising
    # them at runtime via svglib + Cairo + PIL has historically been
    # fragile across reportlab/svglib version combinations — symbols
    # vanishing from the PDF, alpha-channel glitches, and viewBox
    # scaling issues have all bitten this path. To bypass the whole
    # mess we ship pre-rendered PNGs (alpha-channel, 800×800 px,
    # generated once from the canonical SVGs) as static assets next
    # to the SVG files. ReportLab's ``drawImage`` with ``mask='auto'``
    # consumes them directly with no further processing.
    #
    # Only the light theme has a pre-rendered PNG; the dark variant
    # is needed only for in-app rendering, where the browser handles
    # SVG natively and Python never sees the bitmap. If a future
    # caller asks for the dark theme PNG, we fall back to runtime
    # rasterisation.
    if theme == "light":
        png_path = static / f"{code}.png"
        if png_path.exists():
            png_bytes = png_path.read_bytes()
            _ghs_cache[cache_key] = png_bytes
            return png_bytes

    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
    except ImportError:
        log.warning("svglib/renderPM not available — skipping GHS %s", code)
        _ghs_cache[cache_key] = None
        return None

    svg_path = static / f"{code}.svg"
    if not svg_path.exists():
        log.warning("GHS pictogram missing: %s", svg_path)
        _ghs_cache[cache_key] = None
        return None

    palette = _GHS_PALETTES.get(theme, _GHS_PALETTES["light"])
    try:
        raw = svg_path.read_text(encoding="utf-8")
        # Two-step preprocessing:
        #   1. Resolve any ``var(--name, fallback)`` references — used
        #      by the legacy hand-drawn pictograms;
        #   2. Apply theme-aware colour swaps — needed by the official
        #      UN/UNECE pictograms which encode colours directly.
        # Either step is a no-op on SVGs that don't need it, so the
        # pipeline works for both source families without branching.
        resolved = _resolve_css_vars(raw, palette)
        resolved = _apply_theme_colors(resolved, theme)

        # svg2rlg accepts a path or a binary file-like object. Wrapping
        # encoded bytes in BytesIO avoids the
        # "Unicode strings with encoding declaration are not supported"
        # gotcha that StringIO triggers when the SVG has a leading
        # ``<?xml … encoding="utf-8"?>`` declaration.
        d = svg2rlg(io.BytesIO(resolved.encode("utf-8")))

        # The GHS pictograms come from heterogeneous sources with very
        # different viewBox sizes (the official UN SVGs use a 5790×5790
        # canvas, smaller redrawings use 100×100, etc). Rendering at a
        # fixed dpi of 600 against a 5790 viewbox would request a
        # ~48 000 pixel raster from Cairo and fail with "invalid value
        # for size of input". We force the output to a fixed pixel
        # target instead, scaling the Drawing uniformly.
        TARGET_PX = 800
        if d.width and d.height:
            scale = min(TARGET_PX / d.width, TARGET_PX / d.height)
            d.width *= scale
            d.height *= scale
            d.scale(scale, scale)

        # The GHS pictograms are diamond-shaped, but the SVG bounding
        # box is square — without intervention, the four corners end
        # up filled with whatever ``bg`` colour we render against,
        # producing a visible square halo on dark backgrounds.
        #
        # renderPM doesn't generate alpha-channel PNGs natively, so we
        # render against a magenta sentinel and post-process with PIL
        # to swap the sentinel pixels to RGBA alpha=0. This produces
        # a real PNG-with-alpha that ReportLab's ``drawImage(...,
        # mask='auto')`` recognises across all versions — the older
        # color-key approach (``mask=[255,255,0,0,255,255]``) worked
        # on some reportlab builds but on others swallowed the glyph
        # along with the magenta, making the symbol disappear from
        # the printed label.
        from PIL import Image  # noqa: PLC0415 — local keeps cold-import cheap
        pil_img = renderPM.drawToPIL(d, bg=0xFF00FF)
        pil_img = pil_img.convert("RGBA")
        # Walk the bytes once, converting magenta sentinel → fully
        # transparent. Bytes are RGBA-interleaved.
        data = bytearray(pil_img.tobytes())
        for i in range(0, len(data), 4):
            if data[i] == 255 and data[i + 1] == 0 and data[i + 2] == 255:
                # Set alpha to 0; also blank RGB so anti-aliased edges
                # at the diamond border don't bleed magenta when the
                # PDF viewer composites half-transparent pixels.
                data[i + 3] = 0
        pil_img = Image.frombytes("RGBA", pil_img.size, bytes(data))
        buf = io.BytesIO()
        # ``optimize=True`` can make PIL emit a palette PNG with a
        # tRNS chunk, which some PDF viewers handle inconsistently.
        # Force a true RGBA PNG so reportlab's ``mask='auto'`` reads
        # the per-pixel alpha directly.
        pil_img.save(buf, format="PNG", optimize=False)
        png_bytes = buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to rasterise GHS %s (theme=%s): %s",
                    code, theme, exc)
        _ghs_cache[cache_key] = None
        return None

    _ghs_cache[cache_key] = png_bytes
    return png_bytes


def _draw_ghs(c: canvas.Canvas, code: str, x_mm: float, y_mm: float,
              size_mm: float) -> None:
    """Draw a GHS pictogram at ``(x_mm, y_mm)`` (bottom-left), uniformly
    scaled to ``size_mm`` square. No-op if the asset is missing.

    Always uses the ``"light"`` theme: printed labels go on white
    paper regardless of the user's screen settings. The dark palette
    is intended for in-app rendering only.

    The PNG carries a real alpha channel (the diamond's outside
    corners are RGBA(0,0,0,0)), so ``mask='auto'`` lets ReportLab
    composite it correctly on any background. This replaces an
    earlier magenta-colour-key approach that worked unevenly across
    reportlab versions — on some builds the colour key swallowed the
    glyph along with the magenta and the symbol vanished.
    """
    png = _ghs_png(code, theme="light")
    if png is None:
        return
    img = ImageReader(io.BytesIO(png))
    c.drawImage(
        img, x_mm * mm, y_mm * mm,
        width=size_mm * mm, height=size_mm * mm,
        preserveAspectRatio=True,
        mask="auto",
    )


# ── 2D molecule depiction (RDKit, cached) ──────────────────────────


_mol_cache: dict[str, bytes | None] = {}


def _molecule_png(smiles: str | None,
                  *, width_px: int = 700, height_px: int = 600) -> bytes | None:
    """Render a 2D molecular structure as PNG bytes via RDKit.

    Returns None when SMILES is missing, RDKit is unavailable, or the
    string can't be parsed. Cached per process keyed by SMILES — many
    lots of the same substance share a single render.

    The cell aspect ratio (~7:6) gives RDKit room to lay out medium-
    sized molecules without overcrowding while staying close to the
    label's available rectangle on the L7164 format.
    """
    if not smiles:
        return None
    cache_key = f"{smiles}|{width_px}x{height_px}"
    if cache_key in _mol_cache:
        return _mol_cache[cache_key]

    try:
        from rdkit import Chem
        from rdkit.Chem import Draw
    except Exception as exc:  # noqa: BLE001
        log.info("RDKit unavailable, skipping structure: %s", exc)
        _mol_cache[cache_key] = None
        return None

    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            _mol_cache[cache_key] = None
            return None
        img = Draw.MolToImage(mol, size=(width_px, height_px))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png = buf.getvalue()
    except Exception:
        log.exception("Failed to render structure for %s", smiles)
        _mol_cache[cache_key] = None
        return None

    _mol_cache[cache_key] = png
    return png


def _draw_molecule(c: canvas.Canvas, smiles: str | None,
                   x_mm: float, y_mm: float,
                   max_w_mm: float, max_h_mm: float) -> bool:
    """Place a 2D molecule depiction within the given box (bottom-left).

    Returns True if something was drawn, False otherwise — callers can
    decide whether to claim or release the space.
    """
    png = _molecule_png(smiles)
    if png is None:
        return False
    img = ImageReader(io.BytesIO(png))
    c.drawImage(
        img, x_mm * mm, y_mm * mm,
        width=max_w_mm * mm, height=max_h_mm * mm,
        preserveAspectRatio=True, mask="auto",
    )
    return True


# ── Label rendering ────────────────────────────────────────────────


def _truncate(s: str, max_chars: int) -> str:
    """Trim a string to ``max_chars`` chars with an ellipsis if needed."""
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def _fit_to_width(c: canvas.Canvas, text: str, max_w_pt: float,
                  font: str, size: float) -> str:
    """Truncate ``text`` to fit within ``max_w_pt`` at the given font/size.

    Tries word-by-word truncation first, then falls back to character
    truncation when even the first token is too long. The result is
    guaranteed not to overflow ``max_w_pt``.

    The previous implementation returned a bare ellipsis when the text
    contained no whitespace (e.g. comma-separated IUPAC names like
    "1,3,7-trimethylpurine-2,6-dione") because the word-pop loop emptied
    its list and produced "…", which always fits. The fix: only accept
    a word-pop result that retains at least one token; otherwise fall
    through to character-level truncation.
    """
    if not text:
        return ""
    if c.stringWidth(text, font, size) <= max_w_pt:
        return text

    words = text.split()
    # Word-pop: keep removing trailing words until something fits, but
    # require *at least one* word to remain — otherwise we'd return a
    # naked "…" for unsplit strings.
    if len(words) > 1:
        kept = list(words)
        while len(kept) > 1:
            kept.pop()
            candidate = " ".join(kept) + "…"
            if c.stringWidth(candidate, font, size) <= max_w_pt:
                return candidate

    # Either single-token text or even one word is too long — character
    # truncation. Find the longest prefix that fits with an ellipsis.
    for n in range(len(text), 0, -1):
        candidate = text[:n] + "…"
        if c.stringWidth(candidate, font, size) <= max_w_pt:
            return candidate
    return ""


def _wrap_two_lines(c: canvas.Canvas, text: str,
                    max_w_pt: float, font: str, size: float,
                    ) -> tuple[str, str]:
    """Split ``text`` into at most two lines that each fit ``max_w_pt``.

    The first line breaks on the last whitespace whose left fragment
    fits; the second line is truncated with an ellipsis if still too
    long. Returns (line1, line2); line2 is empty if not needed.
    """
    if c.stringWidth(text, font, size) <= max_w_pt:
        return text, ""

    words = text.split()
    line1 = ""
    rest_idx = 0
    for i, w in enumerate(words):
        candidate = (line1 + " " + w).strip()
        if c.stringWidth(candidate, font, size) <= max_w_pt:
            line1 = candidate
            rest_idx = i + 1
        else:
            break

    if not line1:
        # Can't fit even one word — hard truncate by char.
        for n in range(len(words[0]), 0, -1):
            chunk = words[0][:n] + "…"
            if c.stringWidth(chunk, font, size) <= max_w_pt:
                return chunk, " ".join(words[1:])
        return words[0][:1], ""

    line2 = " ".join(words[rest_idx:])
    while line2 and c.stringWidth(line2 + "…", font, size) > max_w_pt:
        line2 = line2.rsplit(" ", 1)[0] if " " in line2 else line2[:-1]
    if line2 and c.stringWidth(line2, font, size) > max_w_pt:
        line2 += "…"
    return line1, line2


def _fit_lot_code_lines(c: canvas.Canvas, text: str, max_w_pt: float,
                        font: str, preferred_size: float,
                        *, min_size: float = 5.0,
                        ) -> tuple[list[str], float]:
    """Shrink-and-wrap a lot code so it ALWAYS fits without truncation.

    The lot code is the lot's primary identifier — losing characters
    to an ellipsis defeats the purpose of printing it. This helper
    therefore never truncates. It tries:

    1. Render at ``preferred_size``: if it fits on a single line, done.
    2. Shrink the font progressively (in 0.25-pt steps) down to
       ``min_size`` looking for a single-line fit at each size.
    3. If even ``min_size`` won't fit one line, wrap to two lines at
       a sensible break point — preferring an existing separator
       (``-``, ``_``, ``/``) inside the lot code, falling back to
       a mid-string character split when the code has no separators.

    Returns ``(lines, font_size)`` where ``lines`` has one or two
    entries. The caller is responsible for laying them out.
    """
    if not text:
        return [""], preferred_size

    # 1. & 2. — try shrinking on a single line.
    size = preferred_size
    while size >= min_size - 0.001:
        if c.stringWidth(text, font, size) <= max_w_pt:
            return [text], size
        size -= 0.25

    # 3. Two-line wrap at the smallest readable size. Prefer breaking
    # at a structural separator that's already in the lot code, in
    # priority order: '-' '_' '/' '.'.  If none works we fall back to
    # a balanced character split (greedy-fit first half, remainder
    # goes to the second line).
    size = min_size
    SEPARATORS = ("-", "_", "/", ".")
    best_split = None
    for sep in SEPARATORS:
        if sep not in text:
            continue
        # Try every occurrence; keep the split closest to the middle
        # whose first half still fits. This balances lines visually.
        positions = [i + 1 for i, ch in enumerate(text) if ch == sep]
        for pos in positions:
            head = text[:pos]
            tail = text[pos:]
            if (c.stringWidth(head, font, size) <= max_w_pt
                    and c.stringWidth(tail, font, size) <= max_w_pt):
                # Prefer the split closest to the midpoint.
                score = abs(pos - len(text) / 2)
                if best_split is None or score < best_split[0]:
                    best_split = (score, head, tail)
        if best_split:
            return [best_split[1], best_split[2]], size

    # No usable separator → balanced character split. Find the longest
    # head that fits, walking back from the midpoint until both halves
    # fit at min_size.
    for split_at in range(len(text) // 2, len(text)):
        head = text[:split_at]
        tail = text[split_at:]
        if (c.stringWidth(head, font, size) <= max_w_pt
                and c.stringWidth(tail, font, size) <= max_w_pt):
            return [head, tail], size

    # Truly pathological case (a single >max_w_pt-wide character): we
    # render anyway at the smallest readable size and accept clipping
    # — but that's better than an ellipsis on the lot code.
    return [text], min_size


def _compute_proportional_shrink(
    c: canvas.Canvas,
    rows: list[tuple[str, str, float, float]],
    *,
    min_ratio: float = 0.55,
) -> float:
    """Find the largest uniform font scale ratio that lets every row fit.

    Args:
        rows: list of ``(text, font, base_size, max_width_pt)`` tuples,
              one per text line that needs to fit on a single line. Empty
              text is ignored.
        min_ratio: floor for the returned ratio. Below this we're getting
              into "illegible" territory (e.g. 7.5pt × 0.55 ≈ 4pt) and
              the caller should fall back to wrapping the offending rows
              instead. Default 0.55 gives a comfortable lower bound for
              the smallest base fonts already in use (5.5–7pt).

    Returns:
        A ratio in [min_ratio, 1.0]. A return value of 1.0 means
        everything fits at the original sizes. Lower means the caller
        should multiply ALL font sizes (and ideally also the
        corresponding line heights) by this factor — every row scales
        together so the visual hierarchy stays intact.

    Rationale:
        Per-row truncation with ellipsis loses information; per-row
        independent shrinking destroys the visual hierarchy (small
        rows shrunk while big rows untouched looks chaotic).  A single
        global scale preserves both: nothing is truncated, and the
        relative sizes of name/lot/iupac/meta/h-p stay proportional —
        a 12-pt name and a 7-pt lot stay in the same 12:7 ratio
        regardless of which row was the bottleneck.
    """
    worst = 1.0
    for text, font, base_size, max_w_pt in rows:
        if not text or max_w_pt <= 0 or base_size <= 0:
            continue
        actual_w = c.stringWidth(text, font, base_size)
        if actual_w <= max_w_pt:
            continue
        # The row needs ratio = max_w / actual_w to fit at this font.
        ratio = max_w_pt / actual_w
        if ratio < worst:
            worst = ratio
    return max(worst, min_ratio)


def _pick_lot_date_label(item: InventoryItem) -> str | None:
    """Choose which date to print on the label for this lot.

    The label has space for one date row; we pick the one most useful
    to the bench operator:

    * **Synthesised lot** (``source_run_id`` set, run completed)
      → ``"Sint: YYYY-MM-DD"`` from the linked Run's
      ``completed_at`` (or ``started_at`` as fallback). For an
      in-house product, knowing when the bottle was made matters
      more than an arbitrary expiry date copied from the precursor.
    * **Purchased lot with explicit expiry** → ``"EXP: YYYY-MM-DD"``
      (the GHS / regulatory norm for purchased reagents).
    * **Purchased lot without expiry but with purchase date**
      → ``"Acq: YYYY-MM-DD"`` so there's still a temporal anchor.
    * **No date information at all** → ``None``; the caller skips
      the row entirely.
    """
    # In-house synthesis: prefer the run's actual completion date.
    if item.source_run_id is not None:
        # Late import to avoid a top-level circular dependency between
        # the labels service and the run model module.
        from stoic_eln.extensions import db  # noqa: PLC0415
        from stoic_eln.models.run import Run  # noqa: PLC0415
        run = db.session.get(Run, item.source_run_id)
        run_date = None
        if run is not None:
            if run.completed_at is not None:
                run_date = run.completed_at.date()
            elif run.started_at is not None:
                run_date = run.started_at.date()
        if run_date is not None:
            return f"Sint: {run_date.isoformat()}"
        # Synthesised lot but the linked run is missing/incomplete: we
        # fall through to the purchased-style fields, which for an
        # in-house lot are usually empty anyway.

    if item.expiry_date is not None:
        return f"EXP: {item.expiry_date.isoformat()}"

    if item.purchased_at is not None:
        return f"Acq: {item.purchased_at.isoformat()}"

    return None


def _draw_label(c: canvas.Canvas, item: InventoryItem,
                origin_x_mm: float, origin_y_mm: float,
                fmt: LabelFormat) -> None:
    """Render one label at the given origin (bottom-left, in mm).

    Layout (patch 12.2): the label is split into a left text column and
    a right "graphics" column (QR + 2D structure stacked).

    Field order, top to bottom in the LEFT column:

      1. Lotto / batch code (small grey)
      2. NAME (bold, large; up to 2 lines)
      3. IUPAC name (italic, small grey)
      4. Molecular formula
      5. CAS
      ── separator ──
      6. MW
      7. Density
      ── separator ──
      8. H phrases (small grey)
      9. P phrases (small grey)
      10. GHS pictograms row
      11. EXP date

    RIGHT column (above the left column's separator-after-CAS line):
      * QR code (15 × 15 mm) — top-right
      * 2D molecular structure (25 × 25 mm) — directly under the QR

    The right column is intentionally narrow now (QR shrunk from 24 mm
    to 15 mm) so the left column gets ~45 mm of usable text width on
    L7164. On the compact formats (L7160, thermal) the right column
    omits the structure (no room) and uses a 14 mm QR.

    Every text row is hard-clamped to the available width via
    ``_fit_to_width`` so nothing ever overlaps the right column or runs
    past the label edge.
    """
    # The lot can belong to either a Substance or a Mixture (XOR
    # constraint). We build a small adapter object exposing the
    # fields the rest of the function reads, so the layout code
    # doesn't have to branch.
    #
    # For a mixture: the "name" includes the primary concentration
    # ("HCl 1N"), the SMILES is None (we don't draw a structure
    # diagram for a mixture — would be ambiguous), GHS comes from
    # the effective view (override or derived), and CAS / formula /
    # MW / density are surfaced from the primary solute when the
    # mixture has a single solute, else left blank.
    sub = item.substance
    mix = item.mixture
    if mix is not None:
        # Build an ad-hoc namespace with the same attribute surface
        # as Substance, so downstream code reads it the same way.
        # We use SimpleNamespace rather than a real class because
        # this is purely a render-time adapter and instances live
        # for one label.
        from types import SimpleNamespace  # noqa: PLC0415
        primary_solute = next(
            (c for c in mix.components if c.role == "solute"),
            None,
        )
        sub = SimpleNamespace(
            name=mix.display_label,
            iupac_name=None,
            cas_number=(
                primary_solute.substance.cas_number
                if primary_solute and primary_solute.substance else None
            ),
            molecular_formula=(
                primary_solute.substance.molecular_formula
                if primary_solute and primary_solute.substance else None
            ),
            molecular_weight=(
                primary_solute.substance.molecular_weight
                if primary_solute and primary_solute.substance else None
            ),
            density=None,                  # mixtures have no single density
            smiles=None,                   # no structure render for mixtures
            ghs_pictograms=mix.effective_pictograms,
            h_phrases=mix.effective_h_phrases,
            p_phrases=mix.effective_p_phrases,
        )
    W = fmt.label_width_mm
    H = fmt.label_height_mm
    pad = 1.5

    is_roomy = H > 50

    # Sizes in mm. Per Rico's patch 12.2 spec, QR shrinks to 15×15 on
    # L7164 (was 24×24) and structure to 25×25 (was 28×22) — both fit
    # vertically inside the right column with room to spare.
    if is_roomy:
        qr_size = 15.0
        struct_w = 25.0
        struct_h = 25.0
        ghs_size = 6.5
        line_h_lot = 3.4
        line_h_name = 4.6
        line_h_iupac = 3.4
        line_h_meta = 3.6
        line_h_hp = 3.2
        line_h_exp = 3.8
        sep_gap = 1.6
        font_lot_size = 7.5
        font_name_size = 11.5
        font_iupac_size = 7.5
        font_meta_size = 8.5
        font_hp_size = 6.8
        font_exp_size = 9.0
    else:
        qr_size = 14.0
        struct_w = 0.0
        struct_h = 0.0
        ghs_size = 5.0
        line_h_lot = 2.5
        line_h_name = 3.5
        line_h_iupac = 2.6
        line_h_meta = 2.7
        line_h_hp = 2.4
        line_h_exp = 2.8
        sep_gap = 0.8
        font_lot_size = 5.8
        font_name_size = 8.5
        font_iupac_size = 6.0
        font_meta_size = 6.5
        font_hp_size = 5.5
        font_exp_size = 7.0

    def at_x(x_mm: float) -> float:
        return (origin_x_mm + x_mm) * mm

    def at_y(y_mm: float) -> float:
        return (origin_y_mm + y_mm) * mm

    # ── Right column: QR + structure ────────────────────────────
    # QR sits in the top-right; structure stacks below it. The bottom
    # of the right column gives us a y-coord above which the left
    # column's text width is constrained, and below which we can use
    # the full label width.
    qr_x_mm = W - qr_size - pad
    qr_y_mm = H - qr_size - pad
    qr = _qr_drawing(qr_payload(item), qr_size)
    renderPDF.draw(qr, c, at_x(qr_x_mm), at_y(qr_y_mm))

    right_col_bottom_mm = qr_y_mm  # if no structure, ends at the QR
    if is_roomy and sub and getattr(sub, "smiles", None):
        # Structure sits under the QR. Centre under the QR if possible,
        # but keep it inside the label — the structure (25 mm) is wider
        # than the QR (15 mm), so it grows to the LEFT past the QR's
        # left edge. Clamp the right edge to the label's right margin.
        ideal_x_mm = qr_x_mm + (qr_size - struct_w) / 2
        max_x_mm = W - struct_w - pad
        struct_x_mm = min(ideal_x_mm, max_x_mm)
        struct_y_mm = qr_y_mm - struct_h - 1.0
        if struct_y_mm > pad:
            if _draw_molecule(c, sub.smiles,
                              origin_x_mm + struct_x_mm,
                              origin_y_mm + struct_y_mm,
                              struct_w, struct_h):
                right_col_bottom_mm = struct_y_mm

    # ── Left column: text width depends on vertical position ────
    # Above the right column's bottom we have only the strip left of
    # the right column; below it we have the full width of the label.
    text_x_mm = pad
    text_x_pt = at_x(text_x_mm)
    # The right column's left edge sets the right boundary above.
    right_col_x_mm = (struct_x_mm if (is_roomy and struct_w
                                      and right_col_bottom_mm < qr_y_mm)
                      else qr_x_mm)
    text_w_top_pt = (right_col_x_mm - pad - 1.0) * mm
    text_w_full_pt = (W - 2 * pad) * mm

    def width_at(y_mm: float) -> float:
        """Available text width at vertical position ``y_mm``.

        Rows that sit even partially above the right column's bottom
        must use the narrow width; anything fully below can spread.
        """
        return text_w_full_pt if y_mm <= right_col_bottom_mm else text_w_top_pt

    # ── Proportional rescale ────────────────────────────────────────
    #
    # Every text row on the label carries information that must be
    # readable in full — truncating with "…" loses the lot code's
    # uniqueness, the IUPAC name, the H/P codes, etc. Rather than
    # truncate independent rows, we compute a SINGLE shrink ratio that
    # makes the longest row fit, then apply that ratio to ALL font
    # sizes and line heights in lockstep. The visual hierarchy
    # (name > meta > lot > hp) is preserved — a 12-pt name shrunk by
    # 0.7 still stands out against a 7-pt lot shrunk by 0.7.
    #
    # We assume each text row uses the *narrow* (top) width, which is
    # a conservative choice: it's right for any row above the right
    # column's bottom (the common case) and only over-estimates the
    # shrink for rows that happen to fall below — which means those
    # rows will fit comfortably with margin to spare. Acceptable
    # trade-off vs the complication of running this twice with the
    # geometry interleaved.
    #
    # The "name" row stays out of this calculation: it has its own
    # two-line wrap path (``_wrap_two_lines``) that's always allowed
    # to use a second line, so it never truncates either way.
    h_codes_for_measure = list((sub.h_phrases if sub else None) or [])
    p_codes_for_measure = list((sub.p_phrases if sub else None) or [])
    date_label_for_measure = _pick_lot_date_label(item)
    iupac_for_measure = (sub.iupac_name if sub else None) or ""
    formula_for_measure = (sub.molecular_formula if sub else None) or ""
    cas_for_measure = (sub.cas_number if sub else None) or ""
    mw_for_measure = (
        f"MW {sub.molecular_weight:.2f}"
        if sub and sub.molecular_weight else ""
    )
    rho_for_measure = (
        f"\u03c1 {sub.density:.3g} g/mL"
        if sub and sub.density else ""
    )

    measure_rows: list[tuple[str, str, float, float]] = []
    if item.batch_code:
        # The "Lotto " prefix counts toward the budget — it has to
        # share the row with the code itself.
        measure_rows.append((
            f"Lotto {item.batch_code}", "Helvetica", font_lot_size,
            text_w_top_pt,
        ))
    if iupac_for_measure:
        measure_rows.append((
            iupac_for_measure, "Helvetica-Oblique", font_iupac_size,
            text_w_top_pt,
        ))
    if formula_for_measure:
        measure_rows.append((
            formula_for_measure, "Helvetica", font_meta_size,
            text_w_top_pt,
        ))
    if cas_for_measure:
        measure_rows.append((
            f"CAS {cas_for_measure}", "Helvetica", font_meta_size,
            text_w_top_pt,
        ))
    if mw_for_measure:
        measure_rows.append((
            mw_for_measure, "Helvetica", font_meta_size,
            text_w_top_pt,
        ))
    if rho_for_measure:
        measure_rows.append((
            rho_for_measure, "Helvetica", font_meta_size,
            text_w_top_pt,
        ))
    if h_codes_for_measure:
        measure_rows.append((
            "H: " + " ".join(h_codes_for_measure),
            "Helvetica", font_hp_size,
            text_w_top_pt,
        ))
    if p_codes_for_measure:
        measure_rows.append((
            "P: " + " ".join(p_codes_for_measure),
            "Helvetica", font_hp_size,
            text_w_top_pt,
        ))
    if date_label_for_measure:
        measure_rows.append((
            date_label_for_measure, "Helvetica-Bold", font_exp_size,
            text_w_full_pt,  # date row is below the right column
        ))

    # Floor the shrink at 0.55: below that, point sizes get into
    # illegible territory (a 5.5-pt font × 0.55 ≈ 3pt). When this
    # floor kicks in, a few exotic-edge-case rows might still need to
    # truncate, but for the practical cases (long lot codes, long
    # IUPAC names, dense H/P phrase lists) 0.55 is more than enough.
    shrink_ratio = _compute_proportional_shrink(
        c, measure_rows, min_ratio=0.55,
    )

    # Apply uniformly to every font and line height. The right-column
    # geometry (QR, structure, GHS pictograms) does NOT scale — those
    # are graphics with their own size logic, and the label's overall
    # layout depends on them being predictable.
    if shrink_ratio < 1.0:
        font_lot_size  *= shrink_ratio
        font_name_size *= shrink_ratio
        font_iupac_size *= shrink_ratio
        font_meta_size *= shrink_ratio
        font_hp_size   *= shrink_ratio
        font_exp_size  *= shrink_ratio
        line_h_lot     *= shrink_ratio
        line_h_name    *= shrink_ratio
        line_h_iupac   *= shrink_ratio
        line_h_meta    *= shrink_ratio
        line_h_hp      *= shrink_ratio
        line_h_exp     *= shrink_ratio
        sep_gap        *= shrink_ratio

    # ── Vertical cursor starts at the top-inner corner ──────────
    cur_y_mm = H - pad

    # ── 1. Lotto / batch code (top, small) ──────────────────────
    #
    # The lot code is the lot's primary identifier — we never truncate
    # it. ``_fit_lot_code_lines`` shrinks the font and falls back to a
    # two-line wrap (preferring breaks at existing separators like
    # '-' '_' '/') so even a long alphanumeric code fits in full.
    if item.batch_code:
        cur_y_mm -= line_h_lot
        c.setFillColor(grey)
        # Reserve "Lotto " prefix in the label, fit only the code so
        # a multi-line wrap stays under the same prefix.
        prefix = "Lotto "
        prefix_w_pt = pdfmetrics.stringWidth(prefix, "Helvetica", font_lot_size)
        avail_pt = width_at(cur_y_mm) - prefix_w_pt
        lines, lot_font_size = _fit_lot_code_lines(
            c, item.batch_code, avail_pt,
            "Helvetica", font_lot_size,
            min_size=max(5.0, font_lot_size - 2.5),
        )
        c.setFont("Helvetica", lot_font_size)
        # First line carries the "Lotto " prefix.
        c.drawString(text_x_pt, at_y(cur_y_mm), prefix + lines[0])
        # Wrapped continuation lines align under the lot code, not the
        # prefix — the prefix is implicit on subsequent rows.
        for extra in lines[1:]:
            cur_y_mm -= line_h_lot
            c.drawString(text_x_pt + prefix_w_pt, at_y(cur_y_mm), extra)
        c.setFillColor(black)

    # ── 2. NAME (bold, big, up to 2 lines) ──────────────────────
    name = (sub.name if sub else "—") or "—"
    line1, line2 = _wrap_two_lines(
        c, name, width_at(cur_y_mm - line_h_name),
        "Helvetica-Bold", font_name_size,
    )
    cur_y_mm -= line_h_name
    c.setFont("Helvetica-Bold", font_name_size)
    c.drawString(text_x_pt, at_y(cur_y_mm), line1)
    if line2:
        cur_y_mm -= line_h_name
        c.drawString(text_x_pt, at_y(cur_y_mm), line2)

    # ── 3. IUPAC name (italic, grey, single line, truncated) ────
    iupac = (sub.iupac_name if sub else None)
    if iupac:
        cur_y_mm -= line_h_iupac
        c.setFont("Helvetica-Oblique", font_iupac_size)
        c.setFillColor(grey)
        c.drawString(
            text_x_pt, at_y(cur_y_mm),
            _fit_to_width(c, iupac, width_at(cur_y_mm),
                          "Helvetica-Oblique", font_iupac_size),
        )
        c.setFillColor(black)

    # ── 4. Molecular formula ────────────────────────────────────
    if sub and sub.molecular_formula:
        cur_y_mm -= line_h_meta
        c.setFont("Helvetica", font_meta_size)
        c.drawString(
            text_x_pt, at_y(cur_y_mm),
            _fit_to_width(c, sub.molecular_formula, width_at(cur_y_mm),
                          "Helvetica", font_meta_size),
        )

    # ── 5. CAS ──────────────────────────────────────────────────
    if sub and sub.cas_number:
        cur_y_mm -= line_h_meta
        c.setFont("Helvetica", font_meta_size)
        c.drawString(
            text_x_pt, at_y(cur_y_mm),
            _fit_to_width(c, f"CAS {sub.cas_number}", width_at(cur_y_mm),
                          "Helvetica", font_meta_size),
        )

    # ── ── separator (thin grey rule across the left column) ─── ──
    # Stop the rule at the left edge of the right column when we're
    # still above its bottom — otherwise it would slice through the
    # QR or 2D structure.
    if sub and (sub.molecular_weight or sub.density):
        cur_y_mm -= sep_gap
        sep_right_mm = (W - pad if cur_y_mm <= right_col_bottom_mm
                        else right_col_x_mm - 1.0)
        c.setStrokeColor(grey)
        c.setLineWidth(0.3)
        c.line(at_x(pad), at_y(cur_y_mm),
               at_x(sep_right_mm), at_y(cur_y_mm))
        c.setStrokeColor(black)

    # ── 6. MW ───────────────────────────────────────────────────
    if sub and sub.molecular_weight:
        cur_y_mm -= line_h_meta
        c.setFont("Helvetica", font_meta_size)
        c.drawString(
            text_x_pt, at_y(cur_y_mm),
            _fit_to_width(c, f"MW {sub.molecular_weight:.2f}",
                          width_at(cur_y_mm),
                          "Helvetica", font_meta_size),
        )

    # ── 7. Density ──────────────────────────────────────────────
    if sub and sub.density:
        cur_y_mm -= line_h_meta
        c.setFont("Helvetica", font_meta_size)
        c.drawString(
            text_x_pt, at_y(cur_y_mm),
            _fit_to_width(c, f"ρ {sub.density:.3g} g/mL",
                          width_at(cur_y_mm),
                          "Helvetica", font_meta_size),
        )

    # ── ── separator before the safety block ────────────────────
    h_codes = list((sub.h_phrases if sub else None) or [])
    p_codes = list((sub.p_phrases if sub else None) or [])
    pictograms = (sub.ghs_pictograms if sub else None) or []
    date_label = _pick_lot_date_label(item)
    if h_codes or p_codes or pictograms or date_label:
        cur_y_mm -= sep_gap
        sep_right_mm = (W - pad if cur_y_mm <= right_col_bottom_mm
                        else right_col_x_mm - 1.0)
        c.setStrokeColor(grey)
        c.setLineWidth(0.3)
        c.line(at_x(pad), at_y(cur_y_mm),
               at_x(sep_right_mm), at_y(cur_y_mm))
        c.setStrokeColor(black)

    # ── 8. H phrases (grey, small) ──────────────────────────────
    if h_codes:
        cur_y_mm -= line_h_hp
        c.setFont("Helvetica", font_hp_size)
        c.setFillColor(grey)
        c.drawString(
            text_x_pt, at_y(cur_y_mm),
            _fit_to_width(c, "H: " + " ".join(h_codes),
                          width_at(cur_y_mm),
                          "Helvetica", font_hp_size),
        )
        c.setFillColor(black)

    # ── 9. P phrases (grey, small) ──────────────────────────────
    if p_codes:
        cur_y_mm -= line_h_hp
        c.setFont("Helvetica", font_hp_size)
        c.setFillColor(grey)
        c.drawString(
            text_x_pt, at_y(cur_y_mm),
            _fit_to_width(c, "P: " + " ".join(p_codes),
                          width_at(cur_y_mm),
                          "Helvetica", font_hp_size),
        )
        c.setFillColor(black)

    # ── 10. GHS pictograms row ──────────────────────────────────
    if pictograms:
        cur_y_mm -= ghs_size + 0.5
        gx_mm = pad
        max_fit = max(1, int((W - 2 * pad) // (ghs_size + 0.7)))
        size = ghs_size
        if len(pictograms) > max_fit:
            size = (W - 2 * pad - 0.7 * (len(pictograms) - 1)) / len(pictograms)
        for code in pictograms:
            _draw_ghs(c, code, origin_x_mm + gx_mm, origin_y_mm + cur_y_mm,
                      size)
            gx_mm += size + 0.7

    # ── 11. Date row (last) ─────────────────────────────────────
    #
    # The label shows ONE date — the most relevant one for this lot:
    #   - synthesised lot   → "Sint: <run completion date>"
    #   - purchased lot     → "EXP: <expiry>"  (or "Acq: <purchase>"
    #                          when no expiry is known)
    # See ``_pick_lot_date_label`` for the priority logic.
    if date_label:
        cur_y_mm -= line_h_exp
        c.setFont("Helvetica-Bold", font_exp_size)
        c.drawString(text_x_pt, at_y(cur_y_mm), date_label)

# ── Public API ─────────────────────────────────────────────────────


def render_labels_pdf(items: Iterable[InventoryItem],
                      fmt_key: str,
                      *,
                      start_position: int = 0,
                      copies_per_item: int = 1,
                      ) -> bytes:
    """Render one or more lots' labels into a PDF.

    Args:
        items: lots to print, in order.
        fmt_key: one of ``LABEL_FORMATS`` keys.
        start_position: zero-based slot index on the first sheet (for
            Avery formats — lets you skip already-used cells on a
            partially-printed sheet). Ignored for thermal.
        copies_per_item: how many copies of each item to emit.

    Returns:
        PDF bytes.
    """
    if fmt_key not in LABEL_FORMATS:
        raise ValueError(f"Unknown label format: {fmt_key!r}")
    fmt = LABEL_FORMATS[fmt_key]

    items_list = list(items)
    if not items_list:
        raise ValueError("No items to print")

    # Expand the queue with copies.
    queue: list[InventoryItem] = []
    for it in items_list:
        for _ in range(copies_per_item):
            queue.append(it)

    buf = io.BytesIO()
    page_size = (fmt.page_width_mm * mm, fmt.page_height_mm * mm)
    c = canvas.Canvas(buf, pagesize=page_size)
    c.setTitle("Stoic — etichette lotti")

    if not fmt.is_sheet:
        # One label per page.
        for it in queue:
            _draw_label(c, it, 0, 0, fmt)
            c.showPage()
    else:
        per_sheet = fmt.per_sheet
        slot = max(0, min(start_position, per_sheet - 1))
        for it in queue:
            row = slot // fmt.cols
            col = slot % fmt.cols
            # Convert from row/col to bottom-left mm coords. ReportLab
            # has origin at bottom-left, but Avery measurements are
            # from the top-left, so we flip the row.
            x_mm = (fmt.margin_left_mm
                    + col * (fmt.label_width_mm + fmt.gap_h_mm))
            y_top_mm = (fmt.margin_top_mm
                        + row * (fmt.label_height_mm + fmt.gap_v_mm))
            y_bottom_mm = (fmt.page_height_mm
                           - y_top_mm - fmt.label_height_mm)
            _draw_label(c, it, x_mm, y_bottom_mm, fmt)
            slot += 1
            if slot >= per_sheet:
                c.showPage()
                slot = 0
        # Close the last partial page.
        if slot != 0:
            c.showPage()

    c.save()
    return buf.getvalue()
