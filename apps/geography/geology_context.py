"""Geological reference data attached to admin boundaries for Terra insights."""

from __future__ import annotations

from typing import Any

from apps.maps.localization import localized_name

from .models import AdminBoundary, BoundaryGeologyDocument, Country

MAX_DOCUMENT_CHARS = 6000
MAX_TOTAL_CHARS = 12000


def _summary_for_locale(boundary: AdminBoundary, locale: str = "en") -> str:
    if locale == "sw" and boundary.geological_summary_sw.strip():
        return boundary.geological_summary_sw.strip()
    return (boundary.geological_summary or "").strip()


def _metadata_lines(metadata: dict | None, locale: str = "en") -> list[str]:
    if not metadata:
        return []
    lines: list[str] = []
    scope = metadata.get("scope")
    if scope:
        label = {"local": "Local", "regional": "Regional", "global": "Global reference"}.get(
            str(scope).lower(), str(scope)
        )
        if locale == "sw":
            label = {
                "local": "Ya ndani",
                "regional": "Ya mkoa",
                "global": "Rejea ya kimataifa",
            }.get(str(scope).lower(), str(scope))
        lines.append(f"Scope: {label}" if locale != "sw" else f"Upeo: {label}")

    field_labels_en = {
        "formations": "Formations",
        "lithology": "Lithology",
        "stratigraphy": "Stratigraphy",
        "tectonic_setting": "Tectonic setting",
        "age": "Age",
        "data_sources": "Data sources",
    }
    field_labels_sw = {
        "formations": "Mifumo ya miamba",
        "lithology": "Litholojia",
        "stratigraphy": "Stratigrafia",
        "tectonic_setting": "Mpangilio wa tektoniki",
        "age": "Umri",
        "data_sources": "Vyanzo vya data",
    }
    labels = field_labels_sw if locale == "sw" else field_labels_en

    for key, label in labels.items():
        raw = metadata.get(key)
        if not raw:
            continue
        if isinstance(raw, list):
            value = ", ".join(str(item) for item in raw if str(item).strip())
        else:
            value = str(raw).strip()
        if value:
            lines.append(f"{label}: {value}")
    return lines


def _boundary_geology_entry(boundary: AdminBoundary, locale: str = "en") -> dict[str, Any] | None:
    summary = _summary_for_locale(boundary, locale)
    metadata = boundary.geological_metadata if isinstance(boundary.geological_metadata, dict) else {}
    docs = list(
        boundary.geology_documents.order_by("-created_at").values(
            "id", "title", "scope", "extracted_text", "created_at"
        )[:8]
    )
    doc_snippets: list[dict[str, Any]] = []
    for doc in docs:
        text = (doc.get("extracted_text") or "").strip()
        if not text:
            continue
        doc_snippets.append(
            {
                "id": doc["id"],
                "title": doc["title"],
                "scope": doc["scope"],
                "excerpt": text[:MAX_DOCUMENT_CHARS],
            }
        )

    if not summary and not metadata and not doc_snippets:
        return None

    level_label = AdminBoundary.Level(boundary.level).label
    return {
        "boundary_id": boundary.id,
        "boundary_name": localized_name(boundary, locale),
        "boundary_level": boundary.level,
        "boundary_level_label": level_label,
        "summary": summary,
        "metadata": metadata,
        "metadata_lines": _metadata_lines(metadata, locale),
        "documents": doc_snippets,
    }


def _boundary_chain(boundary: AdminBoundary) -> list[AdminBoundary]:
    chain: list[AdminBoundary] = []
    current: AdminBoundary | None = boundary
    seen: set[int] = set()
    while current and current.id not in seen:
        chain.append(current)
        seen.add(current.id)
        current = current.parent
    return chain


def geology_context_for_boundary(boundary: AdminBoundary, locale: str = "en") -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for item in _boundary_chain(boundary):
        entry = _boundary_geology_entry(item, locale)
        if entry:
            entries.append(entry)
    return _pack_geology_context(entries, locale)


def geology_context_at_point(
    country_code: str,
    lat: float,
    lng: float,
    *,
    locale: str = "en",
) -> dict[str, Any]:
    from .admin_boundary_service import lookup_boundaries_at_point

    try:
        country = Country.objects.get(code=country_code.upper(), is_active=True)
    except Country.DoesNotExist:
        return {"entries": [], "summary_lines": [], "ai_block": ""}

    lookup = lookup_boundaries_at_point(country, lat, lng)
    boundaries: list[AdminBoundary] = []
    for key in ("village", "ward", "district", "region"):
        ref = lookup.get(key)
        if not ref or not ref.get("id"):
            continue
        boundary = (
            AdminBoundary.objects.filter(id=ref["id"])
            .prefetch_related("geology_documents")
            .first()
        )
        if boundary:
            boundaries.append(boundary)

    entries: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for boundary in boundaries:
        for item in _boundary_chain(boundary):
            if item.id in seen_ids:
                continue
            seen_ids.add(item.id)
            entry = _boundary_geology_entry(item, locale)
            if entry:
                entries.append(entry)

    return _pack_geology_context(entries, locale)


def attach_geological_context(
    ctx: dict,
    *,
    locale: str = "en",
    boundary_id: int | None = None,
) -> dict:
    geology: dict[str, Any] | None = None
    if boundary_id:
        boundary = (
            AdminBoundary.objects.filter(id=boundary_id)
            .prefetch_related("geology_documents")
            .first()
        )
        if boundary:
            geology = geology_context_for_boundary(boundary, locale)
    elif ctx.get("lat") is not None and ctx.get("lng") is not None:
        country_code = (ctx.get("country_code") or "TZ").upper()
        geology = geology_context_at_point(
            country_code,
            float(ctx["lat"]),
            float(ctx["lng"]),
            locale=locale,
        )
    if geology and geology.get("entries"):
        ctx["geological_context"] = geology
    return ctx


def _pack_geology_context(entries: list[dict[str, Any]], locale: str) -> dict[str, Any]:
    if not entries:
        return {"entries": [], "summary_lines": [], "ai_block": ""}

    summary_lines: list[str] = []
    for entry in entries:
        prefix = f"{entry['boundary_level_label']} {entry['boundary_name']}"
        if entry.get("summary"):
            summary_lines.append(f"{prefix}: {entry['summary']}")
        for line in entry.get("metadata_lines") or []:
            summary_lines.append(f"{prefix} — {line}")
        for doc in entry.get("documents") or []:
            excerpt = (doc.get("excerpt") or "").strip()
            if excerpt:
                title = doc.get("title") or "Document"
                summary_lines.append(f"{prefix} — {title}: {excerpt[:400]}")

    ai_block = format_geology_for_ai({"entries": entries, "summary_lines": summary_lines}, locale)
    return {"entries": entries, "summary_lines": summary_lines, "ai_block": ai_block}


def format_geology_for_ai(geology: dict[str, Any], locale: str = "en") -> str:
    entries = geology.get("entries") or []
    if not entries:
        return ""

    lines: list[str] = []
    if locale == "sw":
        lines.append("Muktadha wa kijiolojia kutoka mipaka ya utawala (rejea ya ndani/mkoa/kimataifa):")
    else:
        lines.append("Geological reference from administrative boundaries (local/regional/global context):")

    total_chars = 0
    for entry in entries:
        header = f"- {entry['boundary_level_label']} {entry['boundary_name']}"
        if entry.get("summary"):
            block = f"{header}: {entry['summary']}"
            lines.append(block)
            total_chars += len(block)
        for meta_line in entry.get("metadata_lines") or []:
            block = f"{header} ({meta_line})"
            lines.append(block)
            total_chars += len(block)
        for doc in entry.get("documents") or []:
            excerpt = (doc.get("excerpt") or "").strip()
            if not excerpt:
                continue
            title = doc.get("title") or "Document"
            block = f"{header} — document «{title}»: {excerpt}"
            if total_chars + len(block) > MAX_TOTAL_CHARS:
                remaining = MAX_TOTAL_CHARS - total_chars
                if remaining > 200:
                    lines.append(block[:remaining] + "…")
                break
            lines.append(block)
            total_chars += len(block)
        if total_chars >= MAX_TOTAL_CHARS:
            break

    if locale == "sw":
        lines.append(
            "Tumia muktadha huu wa kijiolojia pamoja na data ya madini iliyopangwa; usibuni taarifa zisizotajwa hapa."
        )
    else:
        lines.append(
            "Use this geological reference together with mapped mineral data; do not invent geology not supported here."
        )
    return "\n".join(lines)
