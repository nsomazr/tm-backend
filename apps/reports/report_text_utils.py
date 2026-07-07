"""Shared report text helpers for findings, citations, and section headings."""

from __future__ import annotations

import re

REFERENCES_HEADING = "References and Sources"
KEY_FINDINGS_HEADING = "Key Findings"


def is_citation_like_finding(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    lower = stripped.lower()
    if re.search(r"https?://", stripped, re.I):
        return True
    if stripped.startswith("[PDF]") or stripped.lower().startswith("[pdf]"):
        return True
    if re.search(r"\.(pdf|docx)\b", stripped, re.I):
        return True
    if re.search(r"\s[-–—]\s*https?://", stripped, re.I):
        return True
    if re.match(r'^".+"\s*$', stripped):
        return True
    if stripped.endswith("..."):
        return True
    if re.search(r":\s*a review\s*$", stripped, re.I):
        return True
    if re.search(
        r"\b(overview of deposits|prospecting in .+ using|mineral resource update|booklet final|technical report summary)\b",
        lower,
    ):
        return True
    if re.search(r"\busing\s+\.\.\.", lower):
        return True
    if len(stripped) > 100 and re.search(
        r"\b(report|study|review|overview of|technical report)\b", lower
    ):
        if not re.search(
            r"\b(should|recommend|risk|potential|drill|exploration|reserve|grade|camp|objective|recovery)\b",
            lower,
        ):
            return True
    return False


def filter_report_findings(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and not is_citation_like_finding(text):
            cleaned.append(text)
    return cleaned


def normalize_section_heading(text: str) -> str:
    stripped = (text or "").strip()
    stripped = re.sub(r"^#+\s*", "", stripped)
    stripped = re.sub(r"^\d+[.)]\s+", "", stripped)
    bold = re.match(r"^\*\*(.+?)\*\*:?\s*$", stripped)
    if bold:
        stripped = bold.group(1).strip()
    hash_heading = re.match(r"^#{1,6}\s+(.+)$", stripped)
    if hash_heading:
        stripped = hash_heading.group(1).strip()
    return stripped
