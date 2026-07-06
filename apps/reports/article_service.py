"""Build structured web article content from report metadata and summary."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from html import unescape


def _strip_html(text: str) -> str:
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


class _SummaryHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks: list[dict] = []
        self._tag: str | None = None
        self._buffer: list[str] = []
        self._list_items: list[str] = []
        self._in_li = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("h2", "h3"):
            self._flush_paragraph()
            self._flush_list()
            self._tag = tag
            self._buffer = []
        elif tag == "p":
            self._flush_paragraph()
            self._flush_list()
            self._tag = "p"
            self._buffer = []
        elif tag in ("ul", "ol"):
            self._flush_paragraph()
            self._flush_list()
            self._tag = "list"
            self._list_items = []
        elif tag == "li":
            self._in_li = True
            self._buffer = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("h2", "h3"):
            text = "".join(self._buffer).strip()
            if text:
                level = 2 if tag == "h2" else 3
                self.blocks.append({"type": "heading", "level": level, "text": text})
            self._tag = None
            self._buffer = []
        elif tag == "p":
            self._flush_paragraph()
        elif tag == "li":
            text = "".join(self._buffer).strip()
            if text:
                self._list_items.append(text)
            self._in_li = False
            self._buffer = []
        elif tag in ("ul", "ol"):
            self._flush_list()

    def handle_data(self, data):
        if self._tag or self._in_li:
            self._buffer.append(data)

    def _flush_paragraph(self):
        if self._tag == "p":
            text = "".join(self._buffer).strip()
            if text:
                self.blocks.append({"type": "paragraph", "text": text})
        self._tag = None
        self._buffer = []

    def _flush_list(self):
        if self._tag == "list" and self._list_items:
            self.blocks.append({"type": "list", "items": self._list_items})
        self._tag = None
        self._list_items = []
        self._buffer = []


def _parse_html_summary(html: str) -> list[dict]:
    parser = _SummaryHtmlParser()
    parser.feed(html)
    parser._flush_paragraph()
    parser._flush_list()
    return parser.blocks


def _parse_plain_summary(text: str) -> list[dict]:
    blocks: list[dict] = []
    for paragraph in [p.strip() for p in text.split("\n\n") if p.strip()]:
        if paragraph in ("Executive Summary", "Key Findings", "Key findings"):
            blocks.append({"type": "heading", "level": 2, "text": paragraph})
            continue
        blocks.append({"type": "paragraph", "text": paragraph})
    return blocks


def build_article_body_from_report(report) -> list[dict]:
    summary = ""
    findings: list[str] = []
    if hasattr(report, "ai_summary") and report.ai_summary:
        summary = report.ai_summary.summary or ""
        findings = list(report.ai_summary.key_findings or [])

    blocks: list[dict] = [
        {"type": "heading", "level": 1, "text": report.title},
    ]

    if report.description:
        blocks.append({"type": "paragraph", "text": report.description.strip()})

    if summary:
        if "<" in summary:
            blocks.extend(_parse_html_summary(summary))
        else:
            blocks.extend(_parse_plain_summary(summary))

    if findings:
        has_findings_heading = any(
            block.get("type") == "heading"
            and str(block.get("text", "")).strip().lower() == "key findings"
            for block in blocks
        )
        if not has_findings_heading:
            blocks.append({"type": "heading", "level": 2, "text": "Key findings"})
        blocks.append({"type": "list", "items": findings})

    mineral_name = report.mineral.name if report.mineral_id else ""
    region_name = report.region.name if report.region_id else ""
    if mineral_name or region_name:
        blocks.append({"type": "heading", "level": 2, "text": "Coverage"})
        meta_parts = []
        if mineral_name:
            meta_parts.append(f"Commodity: {mineral_name}")
        if region_name:
            meta_parts.append(f"Region: {region_name}")
        blocks.append({"type": "paragraph", "text": " · ".join(meta_parts)})

    return blocks


def sync_report_article_body(report, *, force: bool = False) -> bool:
    if not report.has_article:
        return False
    if report.article_body and not force:
        return False
    report.article_body = build_article_body_from_report(report)
    report.save(update_fields=["article_body", "updated_at"])
    return True
