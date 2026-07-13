"""Marketplace listing document upload checks."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

ALLOWED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".doc", ".docx"})
DEFAULT_MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class DocumentValidationError(ValueError):
    """Raised when a listing document fails validation."""


def max_document_bytes() -> int:
    return int(getattr(settings, "MARKETPLACE_DOCUMENT_MAX_BYTES", DEFAULT_MAX_DOCUMENT_BYTES))


def validate_document_upload(filename: str, size: int) -> None:
    name = (filename or "").strip()
    if not name:
        raise DocumentValidationError("Document filename is required.")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise DocumentValidationError("Unsupported file type. Upload a PDF or Word document.")
    if size <= 0:
        raise DocumentValidationError("Document file is empty.")
    limit = max_document_bytes()
    if size > limit:
        mb = max(1, limit // (1024 * 1024))
        raise DocumentValidationError(f"File too large. Maximum size is {mb} MB.")
