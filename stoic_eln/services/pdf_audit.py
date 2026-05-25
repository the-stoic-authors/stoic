"""Stoic — Audit log PDF report (Settimana 6 patch 8).

A landscape-A4 PDF with a multi-page table of audit events. Used by
the admin audit page export button. ReportLab pure-Python so no
extra deps beyond what we already have.
"""

from __future__ import annotations

import json
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Table,
    TableStyle,
)


def _esc(s: str | None) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _header_footer(canvas_obj: canvas.Canvas, doc, *, filters, total_count: int, truncated: bool):
    canvas_obj.saveState()
    w, h = doc.pagesize
    # Header
    canvas_obj.setFont("Times-Bold", 11)
    canvas_obj.drawString(15 * mm, h - 12 * mm, "Stoic — Audit log")
    canvas_obj.setFont("Times-Roman", 8)
    canvas_obj.setFillColor(colors.HexColor("#666"))
    bits = [f"Generato il {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    if filters.date_from or filters.date_to:
        bits.append(f"Date: {filters.date_from or '—'} → {filters.date_to or '—'}")
    if filters.user_id:
        bits.append(f"user_id={filters.user_id}")
    if filters.action:
        bits.append(f"action={filters.action}")
    if filters.entity_type:
        bits.append(f"entity={filters.entity_type}")
    if filters.q:
        bits.append(f'q="{filters.q}"')
    if truncated:
        bits.append(f"⚠ troncato a {len(filters.__dict__) and ''}5000/{total_count}")
    canvas_obj.drawString(15 * mm, h - 16 * mm, "  ·  ".join(bits))

    # Footer
    canvas_obj.setFont("Times-Roman", 8)
    canvas_obj.drawCentredString(
        w / 2.0,
        10 * mm,
        f"pagina {doc.page}",
    )
    canvas_obj.restoreState()


def render_audit_log_pdf(
    *,
    events: list,
    filters,
    label_for_action,
    truncated: bool,
    total_count: int,
) -> bytes:
    """Render the events list as a landscape-A4 PDF."""
    import io

    buf = io.BytesIO()

    page_size = landscape(A4)
    doc = BaseDocTemplate(
        buf,
        pagesize=page_size,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=22 * mm,
        bottomMargin=14 * mm,
        title=f"Stoic — Audit log {datetime.now():%Y-%m-%d}",
        author="Stoic",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="content",
    )

    def _on_page(canvas_obj, doc):
        _header_footer(
            canvas_obj,
            doc,
            filters=filters,
            total_count=total_count,
            truncated=truncated,
        )

    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_on_page)])

    base = getSampleStyleSheet()["BodyText"]
    cell_style = ParagraphStyle("cell", parent=base, fontSize=7, fontName="Times-Roman", leading=9)
    head_style = ParagraphStyle("head", parent=base, fontSize=8, fontName="Times-Bold", leading=10)

    head = [
        Paragraph("Data e ora (UTC)", head_style),
        Paragraph("Utente", head_style),
        Paragraph("Azione", head_style),
        Paragraph("Entità", head_style),
        Paragraph("ID", head_style),
        Paragraph("IP", head_style),
        Paragraph("Dettagli", head_style),
    ]
    rows = [head]
    for e in events:
        label, _c = label_for_action(e.action or "")
        user_name = ""
        if e.user_id:
            from stoic_eln.extensions import db
            from stoic_eln.models.user import User

            u = db.session.get(User, e.user_id)
            user_name = u.full_name if u else f"#{e.user_id}"
        details_json = ""
        if e.details:
            details_json = json.dumps(e.details, ensure_ascii=False)
            if len(details_json) > 240:
                details_json = details_json[:240] + "…"
        rows.append(
            [
                Paragraph(
                    _esc(e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else ""),
                    cell_style,
                ),
                Paragraph(_esc(user_name), cell_style),
                Paragraph(_esc(label), cell_style),
                Paragraph(_esc(e.entity_type or ""), cell_style),
                Paragraph(_esc(str(e.entity_id) if e.entity_id is not None else ""), cell_style),
                Paragraph(_esc(e.ip_address or ""), cell_style),
                Paragraph(_esc(details_json), cell_style),
            ]
        )

    # Column widths (landscape-A4 has ~273 mm of usable width)
    col_widths = [
        32 * mm,  # date
        38 * mm,  # user
        32 * mm,  # action
        24 * mm,  # entity
        14 * mm,  # id
        24 * mm,  # ip
        100 * mm,  # details
    ]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9e9e2")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#888")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f6")]),
            ]
        )
    )

    doc.build([table])
    return buf.getvalue()
