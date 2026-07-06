"""RAG indexing and retrieval for uploaded report PDFs."""

from __future__ import annotations

import math
import re

from django.db import transaction

from .ai_service import _call_report_writing_provider, _model_label, _provider_chain, embed_texts
from .context_extraction import extract_text_from_pages
from .models import Report, ReportDocumentChunk

CHUNK_SIZE = 700
CHUNK_OVERLAP = 100


def _split_text(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return chunks


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def index_report_pdf(report_id: int) -> int:
    report = Report.objects.get(pk=report_id)
    if not report.pdf_file:
        ReportDocumentChunk.objects.filter(report=report).delete()
        return 0

    pages = extract_text_from_pages(report.pdf_file)
    chunk_rows: list[ReportDocumentChunk] = []
    for page_number, page_text in pages:
        for chunk_index, chunk_text in enumerate(_split_text(page_text)):
            chunk_rows.append(
                ReportDocumentChunk(
                    report=report,
                    page_number=page_number,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    token_count=len(chunk_text.split()),
                )
            )

    if not chunk_rows:
        ReportDocumentChunk.objects.filter(report=report).delete()
        return 0

    embeddings = embed_texts([row.text for row in chunk_rows])
    for row, embedding in zip(chunk_rows, embeddings, strict=True):
        row.embedding = embedding

    with transaction.atomic():
        ReportDocumentChunk.objects.filter(report=report).delete()
        ReportDocumentChunk.objects.bulk_create(chunk_rows, batch_size=200)

    return len(chunk_rows)


def retrieve_report_chunks(report: Report, question: str, *, top_k: int = 6) -> list[ReportDocumentChunk]:
    chunks = list(ReportDocumentChunk.objects.filter(report=report))
    if not chunks:
        return []

    query_embedding = embed_texts([question])[0]
    scored = [
        (_cosine_similarity(query_embedding, chunk.embedding or []), chunk)
        for chunk in chunks
    ]
    scored.sort(key=lambda row: row[0], reverse=True)
    return [chunk for score, chunk in scored[:top_k] if score > 0]


REPORT_PDF_CHAT_PROMPT = (
    "You are Terra Meta's report analyst. Answer using ONLY the provided PDF excerpts. "
    "Cite page numbers in square brackets like [Page 3] when referencing content. "
    "If the answer is not in the excerpts, say you cannot find it in the report. "
    "Be concise and geological where appropriate."
)


def answer_report_chat(
    question: str,
    chunks: list[ReportDocumentChunk],
    history: list[dict] | None = None,
) -> tuple[str, str]:
    excerpt_block = "\n\n".join(
        f"[Page {chunk.page_number}]\n{chunk.text}" for chunk in chunks
    )
    user_content = f"PDF excerpts:\n{excerpt_block}\n\nUser question:\n{question.strip()}"
    messages = []
    for item in history or []:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})

    errors: list[str] = []
    for provider in _provider_chain():
        try:
            reply = _call_report_writing_provider(
                provider,
                user_content,
                messages[:-1],
                system_prompt=REPORT_PDF_CHAT_PROMPT,
            )
            if isinstance(reply, dict):
                text = reply.get("assistant_reply") or reply.get("executive_summary") or ""
            else:
                text = str(reply).strip()
            if text:
                return text, _model_label(provider)
        except Exception as exc:
            errors.append(str(exc))

    if chunks:
        first = chunks[0]
        return (
            f"I found related content on [Page {first.page_number}], but could not generate a full answer right now.",
            "fallback",
        )
    raise RuntimeError("; ".join(errors) or "Report chat unavailable")
