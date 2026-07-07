"""Branded prospectivity report PDF generation."""

from __future__ import annotations

import io
import base64
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from .models import Report
from .report_text_utils import KEY_FINDINGS_HEADING, REFERENCES_HEADING, filter_report_findings

_KEY_FINDINGS_HEADING_LOWER = KEY_FINDINGS_HEADING.lower()
_REFERENCES_HEADING_LOWER = REFERENCES_HEADING.lower()


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


def _html_to_report_text(text: str) -> str:
    if not text:
        return ""
    if "<" not in text:
        return text
    cleaned = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    cleaned = re.sub(r"</h[1-6]>", "\n\n", cleaned, flags=re.I)
    cleaned = re.sub(r"</p>", "\n\n", cleaned, flags=re.I)
    cleaned = re.sub(r"</li>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _normalize_color(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "#334155"
    if value.startswith("#"):
        return value[:7]
    rgb = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", value, re.I)
    if rgb:
        r, g, b = (max(0, min(255, int(part))) for part in rgb.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    return value


def _color_from_style(style: str) -> str | None:
    match = re.search(r"color:\s*([^;]+)", style, re.I)
    if not match:
        return None
    return _normalize_color(match.group(1))


def _figure_width_fraction(class_name: str) -> float:
    if "report-editor-figure--width-small" in class_name:
        return 0.25
    if "report-editor-figure--width-large" in class_name:
        return 0.75
    if "report-editor-figure--width-full" in class_name or "report-editor-figure--align-full" in class_name:
        return 1.0
    return 0.5


def _figure_halign(class_name: str) -> str:
    if "report-editor-figure--align-left" in class_name:
        return "LEFT"
    if "report-editor-figure--align-right" in class_name:
        return "RIGHT"
    return "CENTER"


def _decode_image_src(src: str) -> bytes | None:
    src = (src or "").strip()
    if not src:
        return None
    match = re.match(r"data:image/(?:png|jpe?g|gif|webp);base64,(.+)", src, re.I | re.S)
    if match:
        try:
            return base64.b64decode(match.group(1))
        except ValueError:
            return None
    return None


def _open_inline_tag(tag: str, attrs: list[tuple[str, str | None]]) -> str:
    tag = tag.lower()
    attr_map = {key.lower(): value for key, value in attrs}
    if tag in ("b", "strong"):
        return "<b>"
    if tag in ("i", "em"):
        return "<i>"
    if tag == "u":
        return "<u>"
    if tag == "br":
        return "<br/>"
    if tag == "font":
        color = attr_map.get("color")
        if color:
            return f'<font color="{_normalize_color(color)}">'
        return "<font>"
    if tag == "span":
        color = _color_from_style(attr_map.get("style") or "")
        if color:
            return f'<font color="{color}">'
    return ""


def _close_inline_tag(tag: str) -> str:
    tag = tag.lower()
    if tag in ("b", "strong"):
        return "</b>"
    if tag in ("i", "em"):
        return "</i>"
    if tag == "u":
        return "</u>"
    if tag in ("font", "span"):
        return "</font>"
    return ""


class _ReportPdfHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks: list[dict] = []
        self._mode: str | None = None
        self._buffer: list[str] = []
        self._list_items: list[str] = []
        self._in_li = False
        self._li_buffer: list[str] = []
        self._figure_class = ""
        self._figure_src = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_map = {key.lower(): value for key, value in attrs}
        if tag == "figure":
            self._flush()
            self._mode = "figure"
            self._figure_class = attr_map.get("class") or ""
            self._figure_src = ""
            return
        if tag == "img" and self._mode == "figure":
            self._figure_src = attr_map.get("src") or ""
            return
        if tag in ("h2", "h3"):
            self._flush()
            self._mode = tag
            self._buffer = []
            return
        if tag == "p":
            self._flush()
            self._mode = "p"
            self._buffer = []
            return
        if tag in ("ul", "ol"):
            self._flush()
            self._mode = "list"
            self._list_items = []
            return
        if tag == "li":
            self._in_li = True
            self._li_buffer = []
            return
        markup = _open_inline_tag(tag, attrs)
        if not markup:
            return
        if self._in_li:
            self._li_buffer.append(markup)
        elif self._mode in ("p", "h2", "h3"):
            self._buffer.append(markup)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "figure":
            if self._figure_src:
                self.blocks.append(
                    {
                        "type": "image",
                        "src": self._figure_src,
                        "class": self._figure_class,
                    }
                )
            self._mode = None
            self._figure_class = ""
            self._figure_src = ""
            return
        if tag in ("h2", "h3"):
            text = "".join(self._buffer).strip()
            if text:
                self.blocks.append({"type": "heading", "level": 2 if tag == "h2" else 3, "text": text})
            self._mode = None
            self._buffer = []
            return
        if tag == "p":
            markup = "".join(self._buffer).strip()
            if markup:
                self.blocks.append({"type": "paragraph", "markup": markup})
            self._mode = None
            self._buffer = []
            return
        if tag == "li":
            item = "".join(self._li_buffer).strip()
            if item:
                self._list_items.append(item)
            self._in_li = False
            self._li_buffer = []
            return
        if tag in ("ul", "ol"):
            if self._list_items:
                self.blocks.append({"type": "list", "items": self._list_items})
            self._mode = None
            self._list_items = []
            return
        markup = _close_inline_tag(tag)
        if not markup:
            return
        if self._in_li:
            self._li_buffer.append(markup)
        elif self._mode in ("p", "h2", "h3"):
            self._buffer.append(markup)

    def handle_data(self, data):
        if not data:
            return
        escaped = _escape_xml(data)
        if self._in_li:
            self._li_buffer.append(escaped)
        elif self._mode in ("p", "h2", "h3"):
            self._buffer.append(escaped)

    def _flush(self):
        if self._mode == "p":
            markup = "".join(self._buffer).strip()
            if markup:
                self.blocks.append({"type": "paragraph", "markup": markup})
        elif self._mode in ("h2", "h3"):
            text = "".join(self._buffer).strip()
            if text:
                level = 2 if self._mode == "h2" else 3
                self.blocks.append({"type": "heading", "level": level, "text": text})
        elif self._mode == "list" and self._list_items:
            self.blocks.append({"type": "list", "items": self._list_items})
        elif self._mode == "figure" and self._figure_src:
            self.blocks.append(
                {
                    "type": "image",
                    "src": self._figure_src,
                    "class": self._figure_class,
                }
            )
        self._mode = None
        self._buffer = []
        self._list_items = []
        self._in_li = False
        self._li_buffer = []
        self._figure_class = ""
        self._figure_src = ""

    def close(self):
        super().close()
        self._flush()


def _parse_plain_summary_blocks(text: str) -> list[dict]:
    blocks: list[dict] = []
    for paragraph in [part.strip() for part in text.split("\n\n") if part.strip()]:
        if paragraph.lower() == _KEY_FINDINGS_HEADING_LOWER:
            blocks.append({"type": "heading", "level": 2, "text": paragraph})
            continue
        if len(paragraph) < 80 and paragraph == paragraph.title() and " " in paragraph:
            blocks.append({"type": "heading", "level": 2, "text": paragraph})
            continue
        blocks.append({"type": "paragraph", "markup": _escape_xml(paragraph)})
    return blocks


def _parse_summary_html_blocks(summary: str) -> list[dict]:
    if not summary or not summary.strip():
        return []
    if "<" not in summary:
        return _parse_plain_summary_blocks(summary)
    parser = _ReportPdfHtmlParser()
    parser.feed(summary)
    parser.close()
    return parser.blocks


def _split_body_and_findings(blocks: list[dict]) -> tuple[list[dict], list[str]]:
    body: list[dict] = []
    findings: list[str] = []
    in_findings = False

    for block in blocks:
        if block.get("type") == "heading":
            heading = str(block.get("text", "")).strip().lower()
            if heading == _KEY_FINDINGS_HEADING_LOWER:
                in_findings = True
                continue
            if in_findings and heading == _REFERENCES_HEADING_LOWER:
                in_findings = False
                body.append(block)
                continue
        if in_findings:
            if block.get("type") == "list":
                findings.extend(str(item).strip() for item in block.get("items", []) if str(item).strip())
            elif block.get("type") == "paragraph":
                plain = _html_to_report_text(str(block.get("markup", "")))
                if plain:
                    findings.append(plain)
            continue
        body.append(block)

    return body, filter_report_findings(findings)


def _wrap_text(text: str, style: ParagraphStyle) -> Paragraph:
    safe = _escape_xml(text).replace("\n", "<br/>")
    return Paragraph(safe, style)


def _paragraph_markup(markup: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(markup, style)


def _append_summary_blocks(
    story: list,
    blocks: list[dict],
    *,
    section_style: ParagraphStyle,
    subsection_style: ParagraphStyle,
    body_style: ParagraphStyle,
    bullet_style: ParagraphStyle,
    content_width: float,
) -> None:
    for block in blocks:
        block_type = block.get("type")
        if block_type == "heading":
            text = str(block.get("text", "")).strip()
            if not text:
                continue
            style = section_style if block.get("level", 2) <= 2 else subsection_style
            story.append(_wrap_text(text, style))
            continue
        if block_type == "paragraph":
            markup = str(block.get("markup", "")).strip()
            if markup:
                story.append(_paragraph_markup(markup, body_style))
            continue
        if block_type == "list":
            items = [
                ListItem(_paragraph_markup(str(item), bullet_style), leftIndent=12)
                for item in block.get("items", [])
                if str(item).strip()
            ]
            if items:
                story.append(ListFlowable(items, bulletType="bullet", start="•"))
            continue
        if block_type == "image":
            src = str(block.get("src", "")).strip()
            raw = _decode_image_src(src)
            if not raw:
                continue
            class_name = str(block.get("class", ""))
            width = content_width * _figure_width_fraction(class_name)
            try:
                image = Image(io.BytesIO(raw), width=width, height=width * 0.62)
                image.hAlign = _figure_halign(class_name)
                story.append(image)
                story.append(Spacer(1, 0.12 * inch))
            except Exception:
                continue


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
        author="Terra Meta · 5G Geology Futures",
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
    subsection_style = ParagraphStyle(
        "SubsectionHeading",
        parent=section_style,
        fontSize=11.5,
        leading=14,
        textColor=colors.HexColor("#15803d"),
        spaceBefore=12,
        spaceAfter=6,
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
            f"Generated: {timezone.now().strftime('%d %B %Y')} · Terra Meta Mineral Intelligence",
            meta_style,
        )
    )

    if report.description:
        story.append(Spacer(1, 0.1 * inch))
        story.append(_wrap_text("Overview", section_style))
        story.append(_wrap_text(report.description, body_style))

    summary_html = summary_obj.summary if summary_obj else ""
    summary_blocks = _parse_summary_html_blocks(summary_html)
    body_blocks, embedded_findings = _split_body_and_findings(summary_blocks)

    if body_blocks:
        content_width = doc.width
        _append_summary_blocks(
            story,
            body_blocks,
            section_style=section_style,
            subsection_style=subsection_style,
            body_style=body_style,
            bullet_style=bullet_style,
            content_width=content_width,
        )
    elif summary_html:
        plain = _html_to_report_text(summary_html)
        if plain:
            story.append(_wrap_text("Executive summary", section_style))
            for paragraph in plain.split("\n\n"):
                chunk = paragraph.strip()
                if chunk:
                    story.append(_wrap_text(chunk, body_style))

    findings = filter_report_findings(
        list(summary_obj.key_findings if summary_obj and summary_obj.key_findings else [])
    )
    if embedded_findings:
        findings = filter_report_findings(embedded_findings)
    elif not findings and summary_html:
        plain = _html_to_report_text(summary_html)
        findings = [line.strip("- •") for line in plain.split("\n") if line.strip().startswith(("-", "•"))][:12]

    if findings:
        story.append(_wrap_text("Key findings", section_style))
        items = []
        for finding in findings:
            text = str(finding).strip()
            if not text:
                continue
            if "<" in text:
                para = _paragraph_markup(text, bullet_style)
            else:
                para = _wrap_text(text, bullet_style)
            items.append(ListItem(para, leftIndent=12))
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
    story.append(_wrap_text("© Terra Meta · 5G Geology Futures · terrameta.5ggeology.com", meta_style))

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
        canvas.drawString(left, footer_text_y, "Terra Meta · Mineral Intelligence")

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
