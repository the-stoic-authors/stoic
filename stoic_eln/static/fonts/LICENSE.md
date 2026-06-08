# Fonts

This directory contains DejaVu Serif TrueType fonts (regular, bold,
italic, bold italic) used by Stoic's PDF generator to support Unicode
characters not available in ReportLab's built-in Times-Roman family
— in particular subscripts (₂, ₃, ₄), superscripts, Greek letters,
and the typographic characters that occur in free-text fields written
by chemists.

DejaVu fonts are based on Bitstream Vera and are distributed under
the DejaVu license, a free software license. See:
https://dejavu-fonts.github.io/License.html

The font files are bundled here so that PDF generation works
deterministically on any deployment (Mac, Linux x86, Raspberry Pi
ARM) without relying on system-installed fonts.
