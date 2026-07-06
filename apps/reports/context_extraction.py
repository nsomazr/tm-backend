"""Extract plain text from uploaded reference files for report writing context."""

from __future__ import annotations

import io

MAX_CONTEXT_CHARS = 14_000
MAX_INDEX_PAGES = 200


def extract_text_from_upload(uploaded_file) -> str:
    if not uploaded_file:
        return ""

    name = (getattr(uploaded_file, "name", "") or "").lower()
    try:
        if name.endswith(".pdf"):
            return _pdf_text(uploaded_file)
        if name.endswith(".docx"):
            return _docx_text(uploaded_file)
        if name.endswith((".txt", ".md", ".csv")):
            raw = uploaded_file.read()
            if hasattr(uploaded_file, "seek"):
                uploaded_file.seek(0)
            return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""

    return ""


def _pdf_text(uploaded_file) -> str:
    from PyPDF2 import PdfReader

    data = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages[:20]]
    return "\n".join(pages)[:MAX_CONTEXT_CHARS]


def extract_text_from_pages(file_field) -> list[tuple[int, str]]:
    from PyPDF2 import PdfReader

    try:
        reader = PdfReader(file_field.path if hasattr(file_field, "path") else file_field)
    except Exception:
        return []
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages[:MAX_INDEX_PAGES], start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((index, text))
    return pages


def _docx_text(uploaded_file) -> str:
    from docx import Document

    data = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    document = Document(io.BytesIO(data))
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)[:MAX_CONTEXT_CHARS]
