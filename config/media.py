"""Public media URLs and serving (production nginx often proxies only /api/)."""

from __future__ import annotations

from django.conf import settings
from django.http import Http404
from django.urls import reverse

# Sensitive uploads must be served only through authenticated download views.
_BLOCKED_MEDIA_PREFIXES = (
    "reports/",
    "invoices/",
    "receipts/",
    "exploration_reports/",
    "layer_uploads/",
    "layer_imports/",
    "boundary_geology/",
    "ads/",
)


def _normalize_media_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def _is_blocked_media_path(path: str) -> bool:
    normalized = _normalize_media_path(path)
    return any(normalized.startswith(prefix) for prefix in _BLOCKED_MEDIA_PREFIXES)


def public_ad_image_url(request, ad) -> str:
    """Absolute URL for a campaign image under /api/v1/ads/<id>/image/."""
    if not ad or not ad.image:
        return ""
    try:
        if not ad.image.name:
            return ""
    except ValueError:
        return ""
    path = reverse("ad-image", kwargs={"pk": ad.pk})
    if request:
        return request.build_absolute_uri(path)
    base = getattr(settings, "BACKEND_URL", "").rstrip("/")
    if base:
        return f"{base}{path}"
    return path


def public_media_url(request, file_field) -> str:
    """Build an absolute URL under /api/v1/media/ so it is reachable in production."""
    if not file_field:
        return ""
    try:
        name = file_field.name
    except ValueError:
        return ""
    if not name or _is_blocked_media_path(name):
        return ""
    path = reverse("public-media", kwargs={"path": name})
    if request:
        return request.build_absolute_uri(path)
    base = getattr(settings, "BACKEND_URL", "").rstrip("/")
    if base:
        return f"{base}{path}"
    return path


def serve_public_media(request, path):
    """Serve only intentionally public files from MEDIA_ROOT.

    Reports, invoices, exploration PDFs, layer uploads, and ad images must use
    their dedicated authenticated views (e.g. ReportDownloadView, AdImageView).
    """
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise Http404
    if _is_blocked_media_path(path):
        raise Http404
    raise Http404
