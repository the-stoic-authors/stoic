"""Stoic ELN — Run PDF generator (Settimana 5).

Generates a print-ready PDF report of a Run in two flavours:

    render_run_summary(run)  → ~1 page A4 with run header, components,
                               actuals, yield, and notes. The "frontespizio"
                               of a run.

    render_run_full(run)     → multi-page A4 with the full protocol:
                               components, scheme, main reaction (conditions,
                               procedure, checklist), each step (components
                               with absolute amounts, procedure, checklist),
                               yield, notes, post-mortem.

Both share an "academic article" layout: title block on top, sectioned
body, footer with pagination + run code.

The PDF is built using ReportLab Platypus (BaseDocTemplate + Story of
Flowables), which gives us automatic page breaks, headers/footers, and
section flow with no manual coordinate math.

The reaction scheme is rendered with RDKit when available; if RDKit is
not installed the caller-visible flow falls back gracefully to a plain
SMILES text block.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from stoic_eln.services.scheme_image import render_reaction_png
from stoic_eln.services.units import best_fit_mass, best_fit_volume

if TYPE_CHECKING:
    from stoic_eln.models.run import Run

logger = logging.getLogger(__name__)

# ── Layout constants ─────────────────────────────────────────────────────
_PAGE_W, _PAGE_H = A4
_MARGIN_LEFT = 2.0 * cm
_MARGIN_RIGHT = 2.0 * cm
_MARGIN_TOP = 2.0 * cm
_MARGIN_BOTTOM = 2.0 * cm
_FRAME_WIDTH = _PAGE_W - _MARGIN_LEFT - _MARGIN_RIGHT


def _academic_styles() -> dict:
    """Build a paragraph stylesheet with academic-article tone."""
    base = getSampleStyleSheet()

    title = ParagraphStyle(
        "AcademicTitle",
        parent=base["Title"],
        fontName="Times-Bold",
        fontSize=18,
        leading=22,
        alignment=0,  # left
        spaceAfter=4,
    )
    subtitle = ParagraphStyle(
        "AcademicSubtitle",
        parent=base["Normal"],
        fontName="Times-Italic",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#444"),
        spaceAfter=10,
    )
    abstract = ParagraphStyle(
        "AcademicAbstract",
        parent=base["Normal"],
        fontName="Times-Roman",
        fontSize=10,
        leading=13,
        leftIndent=8,
        rightIndent=8,
        spaceBefore=4,
        spaceAfter=14,
        borderPadding=8,
        backColor=colors.HexColor("#f5f5f0"),
        borderColor=colors.HexColor("#d0d0c5"),
        borderWidth=0.5,
    )
    section = ParagraphStyle(
        "AcademicSection",
        parent=base["Heading2"],
        fontName="Times-Bold",
        fontSize=12,
        leading=15,
        spaceBefore=14,
        spaceAfter=4,
        textColor=colors.HexColor("#1a1a1a"),
    )
    subsection = ParagraphStyle(
        "AcademicSubsection",
        parent=base["Heading3"],
        fontName="Times-Bold",
        fontSize=10.5,
        leading=13,
        spaceBefore=8,
        spaceAfter=2,
    )
    body = ParagraphStyle(
        "AcademicBody",
        parent=base["Normal"],
        fontName="Times-Roman",
        fontSize=10,
        leading=13,
        alignment=4,  # justified
        spaceAfter=4,
    )
    body_small = ParagraphStyle(
        "AcademicBodySmall",
        parent=body,
        fontSize=9,
        leading=11,
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=base["Normal"],
        fontName="Times-Roman",
        fontSize=9,
        leading=11,
    )
    mono = ParagraphStyle(
        "AcademicMono",
        parent=body_small,
        fontName="Courier",
        textColor=colors.HexColor("#222"),
    )
    note = ParagraphStyle(
        "AcademicNote",
        parent=body_small,
        textColor=colors.HexColor("#555"),
        fontName="Times-Italic",
    )
    return dict(
        title=title,
        subtitle=subtitle,
        abstract=abstract,
        section=section,
        subsection=subsection,
        body=body,
        body_small=body_small,
        table_cell=table_cell,
        mono=mono,
        note=note,
    )


# ── Helpers ──────────────────────────────────────────────────────────────


def _esc(s: str | None) -> str:
    """Escape special characters for ReportLab Paragraph (XML-like)."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_amount(g: float | None, mL: float | None) -> str:
    """Pick best unit and format an amount as 'X.XXX g' or 'X.XXX mL'."""
    if g is not None:
        f = best_fit_mass(g)
        return f"{f.value:.3f} {f.unit}"
    if mL is not None:
        f = best_fit_volume(mL)
        return f"{f.value:.3f} {f.unit}"
    return "—"


def _component_role_label_it(role: str) -> str:
    return {
        "starting_material": "Materiale di partenza",
        "reactant": "Reattivo",
        "reagent": "Reagente",
        "catalyst": "Catalizzatore",
        "ligand": "Legante",
        "base": "Base",
        "acid": "Acido",
        "oxidant": "Ossidante",
        "reductant": "Riducente",
        "solvent": "Solvente",
        "additive": "Additivo",
        "internal_standard": "Standard interno",
        "product": "Prodotto",
        "byproduct": "Sottoprodotto",
    }.get(role, role)


def _on_page(canvas, doc, *, run, total_pages_callback=None):
    """Draw header (Stoic wordmark + report label) + footer with pagination."""
    canvas.saveState()
    # ── Header ────────────────────────────────────────────────────────
    # Header rule
    canvas.setStrokeColor(colors.HexColor("#888"))
    canvas.setLineWidth(0.4)
    canvas.line(
        _MARGIN_LEFT, _PAGE_H - _MARGIN_TOP + 8, _PAGE_W - _MARGIN_RIGHT, _PAGE_H - _MARGIN_TOP + 8
    )
    # Header left: Stoic wordmark — small caps, modest weight
    canvas.setFont("Times-Bold", 10)
    canvas.setFillColor(colors.HexColor("#0a9ca7"))  # the brand teal accent
    canvas.drawString(_MARGIN_LEFT, _PAGE_H - _MARGIN_TOP + 14, "Stoic")
    canvas.setFillColor(colors.HexColor("#222"))
    canvas.setFont("Times-Roman", 10)
    canvas.drawString(_MARGIN_LEFT + 28, _PAGE_H - _MARGIN_TOP + 14, "ELN")
    # Header right: report kind
    canvas.setFont("Times-Italic", 9)
    canvas.setFillColor(colors.HexColor("#666"))
    canvas.drawRightString(_PAGE_W - _MARGIN_RIGHT, _PAGE_H - _MARGIN_TOP + 14, "Run report")

    # ── Footer ────────────────────────────────────────────────────────
    canvas.setStrokeColor(colors.HexColor("#888"))
    canvas.line(_MARGIN_LEFT, _MARGIN_BOTTOM - 8, _PAGE_W - _MARGIN_RIGHT, _MARGIN_BOTTOM - 8)
    # Footer left: run code
    canvas.setFont("Courier", 8)
    canvas.setFillColor(colors.HexColor("#444"))
    canvas.drawString(_MARGIN_LEFT, _MARGIN_BOTTOM - 18, run.code or "—")
    # Footer right: page X
    canvas.setFont("Times-Roman", 8)
    canvas.drawRightString(
        _PAGE_W - _MARGIN_RIGHT,
        _MARGIN_BOTTOM - 18,
        f"Pagina {doc.page}",
    )
    canvas.restoreState()


# ── Header / abstract block ──────────────────────────────────────────────


def _build_header(run: Run, styles: dict) -> list:
    """The shared 'title block' on page 1."""
    flow = []
    rxn = run.reaction
    template_title = run.template_title_snapshot or (rxn.title if rxn else "")

    flow.append(Paragraph(_esc(template_title) or "Run", styles["title"]))

    bits = [run.code or "—"]
    if run.template_code_snapshot:
        bits.append(f"template <font face='Courier'>{_esc(run.template_code_snapshot)}</font>")
    if run.operator:
        bits.append(f"operatore {_esc(run.operator.operator_code or run.operator.username)}")
    if run.completed_at:
        bits.append(f"completato il {run.completed_at.strftime('%Y-%m-%d')}")
    elif run.started_at:
        bits.append(f"avviato il {run.started_at.strftime('%Y-%m-%d')}")
    flow.append(Paragraph(" · ".join(bits), styles["subtitle"]))

    # Abstract: status + scale + yield in 2-3 lines
    abstract_lines = []
    abstract_lines.append(f"<b>Stato:</b> {_esc(run.status_label_it)}.")
    if run.scale_input_value and run.scale_input_unit:
        abstract_lines.append(
            f"<b>Scala:</b> {run.scale_input_value} {run.scale_input_unit} "
            f"({run.scale_mmol:.3f} mmol)."
        )
    elif run.scale_mmol:
        abstract_lines.append(f"<b>Scala:</b> {run.scale_mmol:.3f} mmol.")
    if run.yield_g is not None:
        if run.yield_percent is not None:
            abstract_lines.append(
                f"<b>Resa:</b> {best_fit_mass(run.yield_g).value:.3f} "
                f"{best_fit_mass(run.yield_g).unit} "
                f"({run.yield_percent:.1f}%)."
            )
        else:
            abstract_lines.append(
                f"<b>Resa:</b> {best_fit_mass(run.yield_g).value:.3f} "
                f"{best_fit_mass(run.yield_g).unit}."
            )
    if run.is_failed:
        abstract_lines.append("<b>Run fallito.</b>")

    flow.append(Paragraph(" ".join(abstract_lines), styles["abstract"]))
    return flow


# ── Components table ─────────────────────────────────────────────────────


def _build_components_table(run: Run, styles: dict, *, full: bool) -> list:
    """Section 1: components used (substance, role, target, actual, lot)."""
    flow: list = []
    flow.append(Paragraph("1. Componenti", styles["section"]))

    if not run.components:
        flow.append(Paragraph("Nessun componente.", styles["note"]))
        return flow

    head_cells = ["Sostanza", "Ruolo", "Eq.", "Quantità target", "Effettiva", "Lotto"]
    rows = [head_cells]
    cell = styles["table_cell"]
    for c in sorted(run.components, key=lambda x: x.position):
        sub = c.substance
        name = sub.name if sub else "?"
        if sub and sub.cas_number:
            name = f"{name} <font size='7' color='#666'>({sub.cas_number})</font>"
        role = _component_role_label_it(c.role)
        eq = ""
        if c.equivalents is not None and c.role not in ("solvent", "product", "byproduct"):
            eq = f"{c.equivalents:g}"
        target = _fmt_amount(c.target_mass_g, c.target_volume_mL)
        actual = _fmt_amount(c.actual_mass_g, c.actual_volume_mL)
        lot = ""
        if c.inventory_item:
            lot = c.inventory_item.batch_code or ""

        rows.append(
            [
                Paragraph(name, cell),
                Paragraph(_esc(role), cell),
                Paragraph(_esc(eq), cell),
                Paragraph(_esc(target), cell),
                Paragraph(_esc(actual), cell),
                Paragraph(f"<font face='Courier'>{_esc(lot)}</font>", cell),
            ]
        )

    col_widths = [
        _FRAME_WIDTH * 0.27,
        _FRAME_WIDTH * 0.16,
        _FRAME_WIDTH * 0.07,
        _FRAME_WIDTH * 0.15,
        _FRAME_WIDTH * 0.15,
        _FRAME_WIDTH * 0.20,
    ]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9e9e2")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#888")),
                ("LINEBELOW", (0, -1), (-1, -1), 0.3, colors.HexColor("#bbb")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ALIGN", (2, 1), (4, -1), "RIGHT"),
            ]
        )
    )
    flow.append(t)
    return flow


# ── Scheme block ─────────────────────────────────────────────────────────


def _build_scheme(run: Run, styles: dict) -> list:
    """Section: reaction scheme (RDKit image, with SMILES fallback)."""
    flow: list = []
    rxn = run.reaction
    if rxn is None:
        return flow

    smiles = ""
    try:
        smiles = rxn.derive_scheme_smiles()
    except Exception:
        logger.exception("derive_scheme_smiles failed")
    if not smiles:
        return flow

    flow.append(Paragraph("2. Schema di reazione", styles["section"]))

    # Try to render an image with RDKit
    png = render_reaction_png(smiles, target_width_px=1400)
    if png is not None:
        try:
            buf = BytesIO(png)
            img = Image(buf)
            # Scale to ≤ frame width while keeping aspect
            iw, ih = img.imageWidth, img.imageHeight
            max_w = _FRAME_WIDTH
            max_h = 6.5 * cm
            ratio = min(max_w / iw, max_h / ih, 1.0)
            img.drawWidth = iw * ratio
            img.drawHeight = ih * ratio
            img.hAlign = "CENTER"
            flow.append(img)
        except Exception:
            logger.exception("Failed to embed scheme image")
            flow.append(
                Paragraph(
                    f"<font face='Courier'>{_esc(smiles)}</font>",
                    styles["mono"],
                )
            )
    else:
        # Fallback: SMILES as text in monospace
        flow.append(
            Paragraph(
                f"<font face='Courier'>{_esc(smiles)}</font>",
                styles["mono"],
            )
        )
    return flow


# ── Reaction-level conditions + procedure + checklist ────────────────────


def _build_main_reaction(run: Run, styles: dict, *, section_no: int) -> list:
    """Section: main reaction (conditions, description, procedure, checklist)."""
    flow: list = []
    rxn = run.reaction
    if rxn is None:
        return flow

    flow.append(Paragraph(f"{section_no}. Reazione principale", styles["section"]))

    # Conditions one-liner
    parts = []
    if rxn.temperature_c is not None:
        parts.append(f"{rxn.temperature_c:g} °C")
    if rxn.duration_hours is not None:
        parts.append(f"{rxn.duration_hours:g} h")
    if rxn.atmosphere:
        atm = {
            "air": "aria",
            "N2": "N₂",
            "Ar": "Ar",
            "vacuum": "vuoto",
            "H2": "H₂",
            "O2": "O₂",
        }.get(rxn.atmosphere, rxn.atmosphere)
        parts.append(atm)
    if rxn.pressure_bar is not None:
        parts.append(f"{rxn.pressure_bar:g} bar")
    if parts:
        flow.append(
            Paragraph(
                f"<b>Condizioni:</b> <font face='Courier'>{_esc(' · '.join(parts))}</font>",
                styles["body_small"],
            )
        )

    if rxn.description:
        flow.append(Paragraph(_esc(rxn.description), styles["body"]))

    if rxn.procedure:
        flow.append(Paragraph("Procedimento", styles["subsection"]))
        flow.append(Paragraph(_esc(rxn.procedure).replace("\n", "<br/>"), styles["body"]))

    if run.checklist_items:
        flow.append(Paragraph("Check list", styles["subsection"]))
        for item in sorted(run.checklist_items, key=lambda x: x.position):
            mark = "☑" if getattr(item, "is_done", False) else "☐"
            flow.append(
                Paragraph(
                    f"{mark} {_esc(item.text)}",
                    styles["body_small"],
                )
            )

    return flow


# ── Steps (workup, extraction, ...) ──────────────────────────────────────


def _build_steps(run: Run, styles: dict, *, section_no: int) -> list:
    """Section: each ReactionStep with components, procedure, checklist."""
    flow: list = []
    if not run.steps:
        return flow

    flow.append(Paragraph(f"{section_no}. Passi", styles["section"]))

    kind_label = {
        "workup": "Workup",
        "extraction": "Estrazione",
        "purification": "Purificazione",
        "analysis": "Analisi",
        "other": "Altro",
    }

    cell = styles["table_cell"]
    for i, step in enumerate(sorted(run.steps, key=lambda x: x.position), 1):
        sub_no = f"{section_no}.{i}"
        title = (
            f"{sub_no} — <i>{_esc(kind_label.get(step.kind, step.kind))}</i> · {_esc(step.title)}"
        )
        flow.append(Paragraph(title, styles["subsection"]))

        if step.components:
            head = ["Sostanza", "Ruolo", "Quantità"]
            rows = [head]
            for sc in sorted(step.components, key=lambda x: x.position):
                sub = sc.substance
                name = sub.name if sub else "?"
                role = _component_role_label_it(sc.role)
                amount = _fmt_amount(sc.actual_mass_g, sc.actual_volume_mL)
                rows.append(
                    [
                        Paragraph(_esc(name), cell),
                        Paragraph(_esc(role), cell),
                        Paragraph(_esc(amount), cell),
                    ]
                )
            t = Table(
                rows,
                colWidths=[
                    _FRAME_WIDTH * 0.45,
                    _FRAME_WIDTH * 0.30,
                    _FRAME_WIDTH * 0.25,
                ],
                repeatRows=1,
            )
            t.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0e9")),
                        ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#888")),
                        ("LINEBELOW", (0, -1), (-1, -1), 0.3, colors.HexColor("#ccc")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                    ]
                )
            )
            flow.append(t)

        if step.description:
            flow.append(Spacer(1, 4))
            flow.append(
                Paragraph(
                    _esc(step.description).replace("\n", "<br/>"),
                    styles["body"],
                )
            )

        if step.checklist_items:
            for item in sorted(step.checklist_items, key=lambda x: x.position):
                mark = "☑" if getattr(item, "is_done", False) else "☐"
                flow.append(
                    Paragraph(
                        f"{mark} {_esc(item.text)}",
                        styles["body_small"],
                    )
                )

    return flow


# ── Notes + post-mortem ──────────────────────────────────────────────────


def _build_cost(run: Run, styles: dict, *, section_no: int) -> list:
    """Section: cost breakdown (Settimana 6 patch 5)."""
    from stoic_eln.services.run_cost import (
        compute_run_cost,
        product_unit_metrics,
    )
    from stoic_eln.services.currency import format_currency

    bd = compute_run_cost(run)
    if not bd.has_data:
        return []

    flow: list = []
    flow.append(Paragraph(f"{section_no}. Costo materiali", styles["section"]))

    summary_parts = []
    if bd.intermediates_total_eur > 0:
        summary_parts.append(
            f"<b>Totale cumulativo:</b> {format_currency(bd.total_eur)} "
            f"<i>(di cui {format_currency(bd.intermediates_total_eur)} di intermedi)</i>"
        )
        summary_parts.append(f"<b>Diretto:</b> {format_currency(bd.direct_total_eur)}")
    else:
        summary_parts.append(f"<b>Totale:</b> {format_currency(bd.total_eur)}")
    if bd.incomplete_count > 0:
        summary_parts.append(f"<i>{bd.incomplete_count} voci senza prezzo (non incluse)</i>")
    flow.append(Paragraph(" · ".join(summary_parts), styles["body"]))

    # Per-unit metrics on the cumulative basis (the meaningful one)
    metrics = product_unit_metrics(run, bd.total_eur)
    if metrics.basis_eur > 0:
        unit_parts = []
        if metrics.per_g is not None:
            unit_parts.append(f"{format_currency(metrics.per_g)}/g")
        if metrics.per_mL is not None:
            unit_parts.append(f"{format_currency(metrics.per_mL)}/mL")
        if metrics.per_mol is not None:
            unit_parts.append(f"{format_currency(metrics.per_mol)}/mol")
        if unit_parts:
            flow.append(
                Paragraph(
                    "<b>Costo unitario del prodotto (cumulativo):</b> " + " · ".join(unit_parts),
                    styles["body"],
                )
            )

    head = ["Sostanza", "Ruolo", "Quantità", "Costo"]
    rows = [head]
    cell = styles["table_cell"]
    for l in bd.lines:
        name = l.substance_name
        if l.source == "step" and l.step_title:
            name = f"<i>[{_esc(l.step_title)}]</i> {_esc(l.substance_name)}"
        else:
            name = _esc(l.substance_name)
        cost_str = format_currency(l.cost_eur, decimals=4) if l.cost_eur is not None else "—"
        rows.append(
            [
                Paragraph(name, cell),
                Paragraph(_esc(l.role), cell),
                Paragraph(_esc(l.actual_quantity_display), cell),
                Paragraph(cost_str, cell),
            ]
        )
    # Footer row
    rows.append(
        [
            Paragraph("<b>TOTALE</b>", cell),
            Paragraph("", cell),
            Paragraph("", cell),
            Paragraph(f"<b>{format_currency(bd.total_eur)}</b>", cell),
        ]
    )

    col_widths = [
        _FRAME_WIDTH * 0.45,
        _FRAME_WIDTH * 0.20,
        _FRAME_WIDTH * 0.15,
        _FRAME_WIDTH * 0.20,
    ]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9e9e2")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#888")),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor("#888")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f5f5f0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ALIGN", (2, 1), (3, -1), "RIGHT"),
            ]
        )
    )
    flow.append(t)
    return flow


def _build_notes(run: Run, styles: dict, *, section_no: int) -> list:
    flow: list = []
    if not run.notes and not run.post_completion_notes:
        return flow
    flow.append(Paragraph(f"{section_no}. Note", styles["section"]))
    if run.notes:
        flow.append(
            Paragraph(
                _esc(run.notes).replace("\n", "<br/>"),
                styles["body"],
            )
        )
    if run.post_completion_notes:
        flow.append(Paragraph("Post-mortem", styles["subsection"]))
        flow.append(
            Paragraph(
                _esc(run.post_completion_notes).replace("\n", "<br/>"),
                styles["body"],
            )
        )
    return flow


def _build_signature_block(run: Run, styles: dict) -> list:
    """Sign-off block with operator + supervisor lines for the lab notebook."""
    flow: list = []
    flow.append(Spacer(1, 18))

    op_name = ""
    op_date = ""
    if run.operator:
        op_name = (
            run.operator.full_name or run.operator.username or run.operator.operator_code or ""
        )
    if run.completed_at:
        op_date = run.completed_at.strftime("%Y-%m-%d")
    elif run.started_at:
        op_date = run.started_at.strftime("%Y-%m-%d")

    cell = styles["table_cell"]
    note_st = ParagraphStyle(
        "SignLabel",
        parent=styles["body_small"],
        fontSize=8,
        textColor=colors.HexColor("#666"),
    )

    # Two-column table: operator (left) | supervisor (right)
    rows = [
        [Paragraph("<b>Operatore</b>", cell), Paragraph("<b>Supervisore</b>", cell)],
        [Paragraph(_esc(op_name) or "&nbsp;", cell), Paragraph("&nbsp;", cell)],
        [Paragraph(_esc(op_date) or "&nbsp;", cell), Paragraph("&nbsp;", cell)],
        [Paragraph("Firma", note_st), Paragraph("Firma", note_st)],
        # Empty row that creates the signature space
        [Paragraph("&nbsp;", cell), Paragraph("&nbsp;", cell)],
    ]

    half = _FRAME_WIDTH / 2 - 4
    t = Table(rows, colWidths=[half, half])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                # Bottom border on row 4 ("Firma" labels) — that's the signature line
                ("LINEBELOW", (0, 3), (-1, 3), 0.6, colors.HexColor("#444")),
                # Vertical separator between operator and supervisor columns
                ("LINEBEFORE", (1, 0), (1, -1), 0.3, colors.HexColor("#bbb")),
                # Make the bottom row tall so there's actual writing space
                ("BOTTOMPADDING", (0, 4), (-1, 4), 28),
            ]
        )
    )
    flow.append(KeepTogether(t))
    return flow


# ── Document assembly ────────────────────────────────────────────────────


def _build_doc(run: Run, flow: list) -> bytes:
    """Wrap a flowables story into a paginated A4 PDF."""
    buf = BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_MARGIN_LEFT,
        rightMargin=_MARGIN_RIGHT,
        topMargin=_MARGIN_TOP,
        bottomMargin=_MARGIN_BOTTOM,
        title=f"Stoic — {run.code}",
        author="Stoic",
    )
    frame = Frame(
        _MARGIN_LEFT,
        _MARGIN_BOTTOM,
        _FRAME_WIDTH,
        _PAGE_H - _MARGIN_TOP - _MARGIN_BOTTOM,
        id="main",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    template = PageTemplate(
        id="Run",
        frames=[frame],
        onPage=lambda c, d, run=run: _on_page(c, d, run=run),
    )
    doc.addPageTemplates([template])
    doc.build(flow)
    return buf.getvalue()


def render_run_summary(run: Run) -> bytes:
    """One-page summary PDF: title, abstract, components, yield/notes, signature."""
    styles = _academic_styles()
    flow: list = []
    flow.extend(_build_header(run, styles))
    flow.extend(_build_components_table(run, styles, full=False))
    # Notes — at section 2 since we skip the scheme/main/steps in summary
    flow.extend(_build_notes(run, styles, section_no=2))
    flow.extend(_build_signature_block(run, styles))
    return _build_doc(run, flow)


def render_run_full(run: Run) -> bytes:
    """Full PDF: everything — components, scheme, main reaction, steps, notes, signature."""
    styles = _academic_styles()
    flow: list = []
    flow.extend(_build_header(run, styles))
    flow.extend(_build_components_table(run, styles, full=True))

    section_no = 2
    scheme_flow = _build_scheme(run, styles)
    if scheme_flow:
        flow.extend(scheme_flow)
        section_no += 1

    flow.extend(_build_main_reaction(run, styles, section_no=section_no))
    section_no += 1

    if run.steps:
        flow.extend(_build_steps(run, styles, section_no=section_no))
        section_no += 1

    cost_flow = _build_cost(run, styles, section_no=section_no)
    if cost_flow:
        flow.extend(cost_flow)
        section_no += 1

    flow.extend(_build_notes(run, styles, section_no=section_no))
    flow.extend(_build_signature_block(run, styles))
    return _build_doc(run, flow)
