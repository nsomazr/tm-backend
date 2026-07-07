"""Professional PDF export for user exploration reports."""

from __future__ import annotations

import io
from datetime import datetime

from django.core.files.base import ContentFile
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from apps.analytics.insight_export import _decode_map_snapshot

from .models import UserExplorationReport
from .pdf_service import _brand_logo_path, _wordmark_path, _wrap_text


def build_exploration_report_pdf(record: UserExplorationReport) -> bytes:
    sections = record.sections or {}
    context = record.context or {}
    map_snapshot = context.get("map_snapshot")

    buffer = io.BytesIO()

    def draw_page(canvas, doc_template):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(0.85 * inch, 0.55 * inch, "Terra Meta · 5G Geology Futures")
        canvas.drawRightString(
            A4[0] - 0.85 * inch,
            0.55 * inch,
            f"Page {canvas.getPageNumber()}",
        )
        wordmark = _wordmark_path()
        if wordmark:
            try:
                canvas.drawImage(
                    str(wordmark),
                    0.85 * inch,
                    A4[1] - 0.65 * inch,
                    width=1.35 * inch,
                    height=0.3 * inch,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception:
                pass
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=1.0 * inch,
        bottomMargin=0.85 * inch,
        title=record.title or "Exploration report",
        author="Terra Meta",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExplorationTitle",
        parent=styles["Heading1"],
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "ExplorationSection",
        parent=styles["Heading2"],
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#166534"),
        spaceBefore=14,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "ExplorationBody",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        textColor=colors.HexColor("#1e293b"),
    )
    meta_style = ParagraphStyle(
        "ExplorationMeta",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748b"),
    )

    story = [
        _wrap_text(record.title or "Geological exploration report", title_style),
        _wrap_text(
            f"Generated {datetime.now().strftime('%d %b %Y')} · {record.user.username if record.user_id else 'User'}",
            meta_style,
        ),
        Spacer(1, 0.2 * inch),
    ]

    section_map = (
        ("executive_summary", "Executive Summary"),
        ("geological_interpretation", "Geological Interpretation"),
        ("layer_analysis", "Layer and Commodity Analysis"),
        ("location_analysis", "Location Analysis"),
        ("analytics_narrative", "Visual Analytics"),
        ("data_references", "Data References"),
    )
    for key, heading in section_map:
        value = sections.get(key)
        if value:
            story.append(_wrap_text(heading, section_style))
            for block in str(value).split("\n\n"):
                if block.strip():
                    story.append(_wrap_text(block.strip(), body_style))
                    story.append(Spacer(1, 0.08 * inch))

    recommendations = sections.get("recommendations") or []
    if recommendations:
        story.append(_wrap_text("Recommendations", section_style))
        for item in recommendations:
            story.append(_wrap_text(f"• {item}", body_style))

    snapshot_bytes = _decode_map_snapshot(map_snapshot)
    if snapshot_bytes:
        story.append(Spacer(1, 0.15 * inch))
        story.append(_wrap_text("Map snapshot", section_style))
        story.append(
            Image(ImageReader(io.BytesIO(snapshot_bytes)), width=6.2 * inch, height=4.0 * inch)
        )

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return buffer.getvalue()


def save_exploration_report_pdf(record: UserExplorationReport) -> UserExplorationReport:
    pdf_bytes = build_exploration_report_pdf(record)
    filename = f"exploration-{record.id}.pdf"
    record.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
    return record
