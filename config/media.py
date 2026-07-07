"""Public media URLs and serving (production nginx often proxies only /api/)."""

from __future__ import annotations

from django.conf import settings
from django.http import Http404
from django.urls import reverse
from django.views.static import serve


def public_media_url(request, file_field) -> str:
    """Build an absolute URL under /api/v1/media/ so it is reachable in production."""
    if not file_field:
        return ""
    try:
        name = file_field.name
    except ValueError:
        return ""
    if not name:
        return ""
    path = reverse("public-media", kwargs={"path": name})
    if request:
        return request.build_absolute_uri(path)
    base = getattr(settings, "BACKEND_URL", "").rstrip("/")
    if base:
        return f"{base}{path}"
    return path


def serve_public_media(request, path):
    """Serve uploaded files from MEDIA_ROOT with path traversal protection."""
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise Http404
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    if getattr(response, "status_code", 200) == 200:
        response["Cache-Control"] = "public, max-age=86400"
    return response
