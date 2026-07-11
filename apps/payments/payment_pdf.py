"""Branded invoice / receipt PDFs (same visual language as Terra Meta reports)."""

from __future__ import annotations

import io
from typing import Literal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.reports.pdf_service import _brand_logo_path, _wordmark_path

from .models import PaymentOrder

DocumentKind = Literal["invoice", "receipt"]

# Match report PDF palette
_SLATE_900 = colors.HexColor("#0f172a")
_SLATE_600 = colors.HexColor("#475569")
_SLATE_500 = colors.HexColor("#64748b")
_SLATE_100 = colors.HexColor("#f1f5f9")
_GREEN_800 = colors.HexColor("#166534")
_GREEN_600 = colors.HexColor("#15803d")
_GREEN_300 = colors.HexColor("#86efac")
_TERRA = colors.HexColor("#0d9488")


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _p(markup: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(markup, style)


def _plain(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_escape(text).replace("\n", "<br/>"), style)


def build_payment_document_pdf(
    *,
    kind: DocumentKind,
    document_number: str,
    order: PaymentOrder,
    description: str,
    issued_date: str,
) -> bytes:
    """Return a formatted A4 PDF for an invoice or receipt."""
    is_receipt = kind == "receipt"
    title = "Receipt" if is_receipt else "Invoice"
    accent = _TERRA if is_receipt else _GREEN_800
    wordmark_path = _wordmark_path()
    icon_path = _brand_logo_path()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=1.15 * inch,
        bottomMargin=0.95 * inch,
        title=f"Terra Meta {title} {document_number}",
        author="Terra Meta · 5G Geology Futures",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PayDocTitle",
        parent=styles["Heading1"],
        fontSize=22,
        leading=26,
        textColor=_SLATE_900,
        spaceAfter=4,
    )
    badge_style = ParagraphStyle(
        "PayDocBadge",
        parent=styles["Normal"],
        fontSize=10,
        leading=13,
        textColor=accent,
        spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "PayDocSection",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        textColor=_GREEN_800,
        spaceBefore=14,
        spaceAfter=8,
    )
    label_style = ParagraphStyle(
        "PayDocLabel",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=_SLATE_500,
        spaceAfter=1,
    )
    value_style = ParagraphStyle(
        "PayDocValue",
        parent=styles["Normal"],
        fontSize=10.5,
        leading=14,
        textColor=_SLATE_900,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "PayDocBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6,
    )
    amount_style = ParagraphStyle(
        "PayDocAmount",
        parent=styles["Normal"],
        fontSize=16,
        leading=20,
        textColor=accent,
        alignment=TA_RIGHT,
        fontName="Helvetica-Bold",
    )
    meta_style = ParagraphStyle(
        "PayDocMeta",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=_SLATE_500,
    )
    cell_label = ParagraphStyle(
        "PayCellLabel",
        parent=styles["Normal"],
        fontSize=8,
        textColor=_SLATE_500,
    )
    cell_value = ParagraphStyle(
        "PayCellValue",
        parent=styles["Normal"],
        fontSize=10,
        textColor=_SLATE_900,
    )
    cell_value_right = ParagraphStyle(
        "PayCellValueRight",
        parent=cell_value,
        alignment=TA_RIGHT,
    )

    customer_name = order.user.get_full_name() or order.user.username or "Customer"
    customer_email = order.user.email or "—"
    amount_display = f"{order.amount} {order.currency}"
    status_display = (order.status or "").replace("_", " ").title()
    provider_display = (order.payment_provider or "").replace("_", " ").title()
    order_type_display = (order.order_type or "").replace("_", " ").title()

    story: list = []

    # Document type chip + title
    story.append(_plain(title.upper(), badge_style))
    story.append(_plain(f"Terra Meta {title}", title_style))
    story.append(
        _p(
            f"Document <b>{_escape(document_number)}</b> · Issued {_escape(issued_date)}",
            body_style,
        )
    )

    story.append(
        HRFlowable(
            width="100%",
            thickness=1.25,
            color=_GREEN_300,
            spaceBefore=4,
            spaceAfter=12,
        )
    )

    # Bill-to / document meta side by side
    left_meta = [
        Paragraph("BILL TO", label_style),
        Paragraph(_escape(customer_name), value_style),
        Paragraph(_escape(customer_email), body_style),
    ]
    right_meta = [
        Paragraph("ORDER REFERENCE", label_style),
        Paragraph(f"<font face='Courier' size='9'>{_escape(str(order.merchant_reference))}</font>", value_style),
        Paragraph("PAYMENT TYPE", label_style),
        Paragraph(_escape(order_type_display), value_style),
    ]
    meta_table = Table(
        [[left_meta, right_meta]],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(meta_table)

    story.append(_plain("Summary", section_style))

    # Line-item style table
    rows = [
        [
            Paragraph("<b>Description</b>", cell_label),
            Paragraph("<b>Status</b>", cell_label),
            Paragraph("<b>Provider</b>", cell_label),
            Paragraph("<b>Amount</b>", cell_label),
        ],
        [
            Paragraph(_escape(description or "Terra Meta payment"), cell_value),
            Paragraph(_escape(status_display), cell_value),
            Paragraph(_escape(provider_display), cell_value),
            Paragraph(_escape(amount_display), cell_value_right),
        ],
    ]
    detail = Table(rows, colWidths=[doc.width * 0.42, doc.width * 0.18, doc.width * 0.18, doc.width * 0.22])
    detail.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _SLATE_100),
                ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(detail)
    story.append(Spacer(1, 0.2 * inch))

    total_table = Table(
        [
            [
                Paragraph("Total due" if not is_receipt else "Amount paid", label_style),
                Paragraph(_escape(amount_display), amount_style),
            ]
        ],
        colWidths=[doc.width * 0.55, doc.width * 0.45],
    )
    total_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
                ("BOX", (0, 0), (-1, -1), 1, _GREEN_300),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(total_table)

    story.append(Spacer(1, 0.28 * inch))
    if is_receipt:
        note = (
            "This receipt confirms payment received by Terra Meta. "
            "Retain it for your records. For billing questions contact support via the Terra Meta platform."
        )
    else:
        note = (
            "This invoice was issued by Terra Meta · 5G Geology Futures. "
            "Payment status reflects the current order state on the platform."
        )
    story.append(_plain(note, meta_style))
    story.append(Spacer(1, 0.1 * inch))
    story.append(
        _plain("© Terra Meta · 5G Geology Futures · terrameta.5ggeology.com", meta_style)
    )

    def _draw_page(canvas, doc_template):
        canvas.saveState()
        left = doc.leftMargin
        right = A4[0] - doc.rightMargin
        page_top = A4[1]

        if wordmark_path:
            wordmark_w = 2.35 * inch
            wordmark_h = 0.5 * inch
            wordmark_y = page_top - doc.topMargin + 0.22 * inch
            try:
                canvas.drawImage(
                    str(wordmark_path),
                    left,
                    wordmark_y,
                    width=wordmark_w,
                    height=wordmark_h,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception:
                canvas.setFont("Helvetica-Bold", 14)
                canvas.setFillColor(_GREEN_800)
                canvas.drawString(left, wordmark_y + 0.12 * inch, "Terra Meta")
            line_y = wordmark_y - 0.1 * inch
        else:
            canvas.setFont("Helvetica-Bold", 14)
            canvas.setFillColor(_GREEN_800)
            canvas.drawString(left, page_top - doc.topMargin + 0.35 * inch, "Terra Meta")
            line_y = page_top - doc.topMargin + 0.18 * inch

        if icon_path and wordmark_path:
            try:
                canvas.drawImage(
                    str(icon_path),
                    right - 0.42 * inch,
                    page_top - doc.topMargin + 0.28 * inch,
                    width=0.38 * inch,
                    height=0.38 * inch,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception:
                pass

        canvas.setStrokeColor(_GREEN_300)
        canvas.setLineWidth(0.9)
        canvas.line(left, line_y, right, line_y)

        # Accent bar under header
        canvas.setStrokeColor(accent)
        canvas.setLineWidth(2.2)
        canvas.line(left, line_y - 2.5, left + 1.4 * inch, line_y - 2.5)

        footer_y = 0.42 * inch
        canvas.setStrokeColor(colors.HexColor("#e2e8f0"))
        canvas.setLineWidth(0.6)
        canvas.line(left, footer_y + 0.22 * inch, right, footer_y + 0.22 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_SLATE_500)
        canvas.drawString(left, footer_y, "Terra Meta · 5G Geology Futures")
        canvas.drawRightString(right, footer_y, f"{title} · {document_number}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return buffer.getvalue()
