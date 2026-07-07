"""RAG indexing and retrieval for uploaded report PDFs."""

from __future__ import annotations

import logging
import math
import re

from django.db import transaction

from .ai_service import (
    _call_chat_provider,
    _model_label,
    _provider_chain,
    embed_texts,
    friendly_provider_error,
)
from .context_extraction import extract_text_from_pages
from .models import Report, ReportDocumentChunk

logger = logging.getLogger(__name__)

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
        logger.warning("Report %s PDF produced no extractable text for chat indexing", report_id)
        return 0

    embeddings = embed_texts([row.text for row in chunk_rows])
    for row, embedding in zip(chunk_rows, embeddings, strict=True):
        row.embedding = embedding

    with transaction.atomic():
        ReportDocumentChunk.objects.filter(report=report).delete()
        ReportDocumentChunk.objects.bulk_create(chunk_rows, batch_size=200)

    logger.info("Indexed %s PDF chunks for report %s", len(chunk_rows), report_id)
    return len(chunk_rows)


def ensure_report_indexed(report: Report) -> int:
    """Build the PDF search index on demand (Celery indexing may not have run yet)."""
    if not report.pdf_file:
        return 0
    existing = ReportDocumentChunk.objects.filter(report=report).count()
    if existing:
        return existing
    return index_report_pdf(report.id)


def _keyword_rank_chunks(chunks: list[ReportDocumentChunk], question: str, *, top_k: int) -> list[ReportDocumentChunk]:
    terms = [term.lower() for term in re.findall(r"[a-z0-9]{3,}", question.lower())]
    if not terms:
        return chunks[:top_k]

    def score(chunk: ReportDocumentChunk) -> int:
        text = chunk.text.lower()
        return sum(text.count(term) for term in terms)

    ranked = sorted(chunks, key=score, reverse=True)
    if score(ranked[0]) <= 0:
        return sorted(chunks, key=lambda row: (row.page_number, row.chunk_index))[:top_k]
    return ranked[:top_k]


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
    selected = [chunk for score, chunk in scored[:top_k] if score > 0]
    if not selected:
        selected = _keyword_rank_chunks(chunks, question, top_k=top_k)
    return selected[:top_k]


REPORT_PDF_CHAT_PROMPT = (
    "You are Terra Meta's report analyst. Answer ONLY from the PDF excerpts in Reference context. "
    "Quote specific facts, names, numbers, and locations from the document. "
    "Cite page numbers in square brackets like [Page 3] for every claim. "
    "If the excerpts do not contain the answer, say: \"I cannot find that in this report.\" "
    "Do not invent generic geology or use outside knowledge. Be concise."
)


def answer_report_chat(
    question: str,
    chunks: list[ReportDocumentChunk],
    history: list[dict] | None = None,
) -> tuple[str, str]:
    excerpt_block = "\n\n".join(
        f"[Page {chunk.page_number}]\n{chunk.text}" for chunk in chunks
    )
    if not excerpt_block.strip():
        return (
            "I cannot read text from this PDF yet. The document may be scanned, still indexing, "
            "or empty — try again shortly or re-upload a text-based PDF.",
            "fallback",
        )

    context = f"PDF excerpts:\n{excerpt_block}"
    chat_messages: list[dict[str, str]] = []
    for item in history or []:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            chat_messages.append({"role": role, "content": content})
    chat_messages.append({"role": "user", "content": question.strip()})

    errors: list[str] = []
    chain = _provider_chain()
    if not chain:
        raise RuntimeError(
            "No AI providers are available. Configure GROQ_API_KEY, GEMINI_API_KEY, or a running Ollama server."
        )

    logger.info("Report chat provider chain: %s", " -> ".join(chain))

    for provider in chain:
        try:
            reply = _call_chat_provider(
                provider,
                chat_messages,
                context,
                system_prompt=REPORT_PDF_CHAT_PROMPT,
            )
            text = str(reply).strip()
            if text:
                return text, _model_label(provider)
            errors.append(f"{provider}: empty response")
        except Exception as exc:
            logger.warning("Report chat provider %s failed: %s", provider, exc)
            errors.append(friendly_provider_error(provider, exc))

    if chunks:
        first = chunks[0]
        return (
            f"I found related content on [Page {first.page_number}], but could not generate a full answer right now.",
            "fallback",
        )
    raise RuntimeError("; ".join(errors) or "Report chat unavailable")
