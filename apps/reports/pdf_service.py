"""Branded prospectivity report PDF generation."""

from __future__ import annotations

import io
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from .models import Report


def _brand_logo_path() -> Path | None:
    custom = getattr(settings, "REPORT_PDF_LOGO", "").strip()
    if custom:
        path = Path(custom)
        if path.is_file():
            return path
    for candidate in (
        Path(settings.BASE_DIR) / "static" / "branding" / "terrameta-logo-icon.png",
        Path(settings.BASE_DIR).parent / "tm-frontend" / "public" / "terrameta-logo-icon.png",
    ):
        if candidate.is_file():
            return candidate
    return None


def _wordmark_path() -> Path | None:
    for candidate in (
        Path(settings.BASE_DIR) / "static" / "branding" / "logo-word.png",
        Path(settings.BASE_DIR).parent / "tm-frontend" / "public" / "logo-word.png",
    ):
        if candidate.is_file():
            return candidate
    return None


def _wrap_text(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(safe, style)


def build_report_pdf_bytes(report: Report) -> bytes:
    report = Report.objects.select_related("mineral", "region").prefetch_related("ai_summary").get(pk=report.pk)
    summary_obj = getattr(report, "ai_summary", None)

    wordmark_path = _wordmark_path()
    icon_path = _brand_logo_path()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=1.05 * inch,
        bottomMargin=0.95 * inch,
        title=report.title,
        author="Terra Meta · 5G Geology",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#475569"),
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#166534"),
        spaceBefore=16,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontSize=10.5,
        leading=15,
        textColor=colors.HexColor("#334155"),
        alignment=TA_JUSTIFY,
        spaceAfter=8,
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748b"),
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        parent=body_style,
        leftIndent=12,
        bulletIndent=0,
        spaceAfter=4,
    )

    story: list = []

    story.append(_wrap_text(report.title, title_style))

    mineral_name = report.mineral.name if report.mineral_id else "N/A"
    region_name = report.region.name if report.region_id else "National"
    story.append(_wrap_text(f"Mineral: {mineral_name}", subtitle_style))
    story.append(_wrap_text(f"Region: {region_name}", subtitle_style))
    story.append(
        _wrap_text(
            f"Generated: {timezone.now().strftime('%d %B %Y')} · Terra Meta Mineral Intelligence Platform",
            meta_style,
        )
    )

    if report.description:
        story.append(Spacer(1, 0.1 * inch))
        story.append(_wrap_text("Overview", section_style))
        story.append(_wrap_text(report.description, body_style))

    summary_text = summary_obj.summary if summary_obj else ""
    summary_body = summary_text
    if summary_text:
        for marker in ("Key findings:", "key findings:", "KEY FINDINGS:"):
            if marker in summary_text:
                summary_body = summary_text.split(marker, 1)[0].strip()
                break

    if summary_body:
        story.append(_wrap_text("Executive summary", section_style))
        for paragraph in summary_body.split("\n\n"):
            chunk = paragraph.strip()
            if chunk:
                story.append(_wrap_text(chunk, body_style))

    findings = summary_obj.key_findings if summary_obj and summary_obj.key_findings else []
    if not findings and summary_text:
        findings = [line.strip("- •") for line in summary_text.split("\n") if line.strip().startswith(("-", "•"))][:8]

    if findings:
        story.append(_wrap_text("Key findings", section_style))
        items = [
            ListItem(_wrap_text(str(finding), bullet_style), leftIndent=12)
            for finding in findings
            if str(finding).strip()
        ]
        if items:
            story.append(ListFlowable(items, bulletType="bullet", start="•"))

    story.append(Spacer(1, 0.25 * inch))
    story.append(
        _wrap_text(
            "This report is part of the Terra Meta prospectivity catalog. "
            "Data and interpretations support exploration planning and due diligence; "
            "verify critical decisions with licensed geological survey and field work.",
            meta_style,
        )
    )
    story.append(Spacer(1, 0.12 * inch))
    story.append(_wrap_text("© Terra Meta · 5G Geology · terrameta.5ggeology.com", meta_style))

    def _draw_page(canvas, doc_template):
        canvas.saveState()
        left = doc.leftMargin
        right = A4[0] - doc.rightMargin
        page_top = A4[1]

        if wordmark_path:
            wordmark_w = 2.35 * inch
            wordmark_h = 0.5 * inch
            wordmark_y = page_top - doc.topMargin + 0.18 * inch
            canvas.drawImage(
                str(wordmark_path),
                left,
                wordmark_y,
                width=wordmark_w,
                height=wordmark_h,
                preserveAspectRatio=True,
                mask="auto",
            )
            line_y = wordmark_y - 0.1 * inch
            canvas.setStrokeColor(colors.HexColor("#86efac"))
            canvas.setLineWidth(0.75)
            canvas.line(left, line_y, right, line_y)
        else:
            canvas.setFont("Helvetica-Bold", 14)
            canvas.setFillColor(colors.HexColor("#166534"))
            canvas.drawString(left, page_top - doc.topMargin + 0.35 * inch, "Terra Meta")

        footer_text_y = 0.42 * inch
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(left, footer_text_y, "Terra Meta · Mineral Intelligence Platform")

        page_label = f"Page {doc_template.page}"
        icon_size = 0.42 * inch
        icon_x = right - icon_size

        if icon_path:
            icon_y = footer_text_y - 0.06 * inch
            canvas.drawImage(
                str(icon_path),
                icon_x,
                icon_y,
                width=icon_size,
                height=icon_size,
                preserveAspectRatio=True,
                mask="auto",
            )
            canvas.drawRightString(icon_x - 0.12 * inch, footer_text_y, page_label)
        else:
            canvas.drawRightString(right, footer_text_y, page_label)

        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return buffer.getvalue()


def ensure_report_pdf(report: Report, *, force: bool = False) -> Report:
    """Generate and save PDF if missing (or when force=True). Returns refreshed report."""
    if report.pdf_file and not force:
        return report

    pdf_bytes = build_report_pdf_bytes(report)
    filename = f"{report.slug}.pdf"
    report.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
    return report
