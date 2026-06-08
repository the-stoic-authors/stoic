"""Stoic ELN — PDF font registration.

Registers DejaVu Serif (regular + 3 variants) with ReportLab so the
PDF generators can render Unicode characters that the built-in
Times-Roman family doesn't cover.

Built-in fonts in ReportLab's standard set (Times-Roman, Helvetica,
Courier, ...) only have a Latin-1 character set. Anything outside —
subscripts (₂, ₃, ₄, ...), superscripts, Greek letters, em-dashes
in some encodings, typographic quotes — renders as a "tofu" black
square in the PDF.

For a chemistry app this matters: chemists write Na₂SO₄, NaHCO₃,
α-pinene, β-naphthol, etc. all the time in free-text fields. PubChem
imports formulas with these too.

DejaVu Serif covers all the codepoints that appear in chemistry
practice (subscripts, superscripts, Greek, IPA, ...) and is bundled
in ``stoic_eln/static/fonts/``. We register it once at import time
under the family name ``DejaVuSerif`` with the four standard
variants, then expose constants for the font names so the PDF
modules can pick them up.

Idempotent: re-registering a font is a no-op in ReportLab.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Font names that PDF modules import — keep these stable.
FONT_REGULAR = "StoicSerif"
FONT_BOLD = "StoicSerif-Bold"
FONT_ITALIC = "StoicSerif-Italic"
FONT_BOLD_ITALIC = "StoicSerif-BoldItalic"

_FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"

_REGISTERED = False


def register() -> None:
    """Register the Stoic PDF font family with ReportLab.

    Safe to call multiple times. The first call performs the
    registration; subsequent calls return immediately.
    """
    global _REGISTERED
    if _REGISTERED:
        return

    variants = [
        (FONT_REGULAR, "DejaVuSerif.ttf"),
        (FONT_BOLD, "DejaVuSerif-Bold.ttf"),
        (FONT_ITALIC, "DejaVuSerif-Italic.ttf"),
        (FONT_BOLD_ITALIC, "DejaVuSerif-BoldItalic.ttf"),
    ]

    for name, filename in variants:
        path = _FONT_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Stoic PDF font missing: {path}. The DejaVu Serif "
                f"family must be bundled at {_FONT_DIR}/."
            )
        pdfmetrics.registerFont(TTFont(name, str(path)))

    # Register the family so ReportLab honours <b>, <i>, <b><i> tags
    # in Paragraph markup by swapping to the right variant automatically.
    pdfmetrics.registerFontFamily(
        FONT_REGULAR,
        normal=FONT_REGULAR,
        bold=FONT_BOLD,
        italic=FONT_ITALIC,
        boldItalic=FONT_BOLD_ITALIC,
    )

    _REGISTERED = True
