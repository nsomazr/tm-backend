"""Build Terra insight export PDFs for paid subscribers (Ask Terra report mode)."""

from __future__ import annotations

import base64
import io
import re
from datetime import datetime
from typing import Any

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.maps.access import user_has_map_detail_access
from apps.maps.models import MapFeature
from apps.reports.ai_service import generate_map_insight, sanitize_assistant_output
from apps.reports.pdf_service import _brand_logo_path, _wordmark_path

from .coverage_stats import build_feature_coverage_stats
from .insights import (
    area_location_context,
    build_area_ai_context,
    build_search_ai_context,
    layer_coverage_context,
    mineral_coverage_context,
    region_coverage_context,
)

DEFAULT_SECTIONS = ("overview", "minerals", "regions", "analytics", "chat")

EXPORT_NARRATIVE_PROMPT = (
    "You are Terra Meta's mineral intelligence report writer. Using ONLY the structured data below, "
    "write a professional brief suitable for 3–5 printed pages (roughly 900–1400 words). "
    "Use these section headings on their own lines: Executive Summary, Mineral Coverage, "
    "Regional Distribution, Analysis & Trends, Recommendations. "
    "Write in clear paragraphs for investors and exploration teams. "
    "Cite specific numbers, regions, and minerals from the data. "
    "Do not invent reserves, licenses, or drill results. "
    "If data is limited, state that clearly."
)


def _decode_map_snapshot(raw: str | None) -> bytes | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    match = re.match(r"data:image/(?:png|jpeg|jpg);base64,(.+)", text, re.DOTALL | re.IGNORECASE)
    payload = match.group(1) if match else text
    try:
        data = base64.b64decode(payload, validate=True)
        return data if data else None
    except Exception:
        return None


def _wrap_text(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(safe, style)


def _normalize_sections(sections: list[str] | None) -> list[str]:
    if not sections:
        return list(DEFAULT_SECTIONS)
    allowed = {"overview", "minerals", "regions", "analytics", "chat", "map_snapshot"}
    out = [s for s in sections if s in allowed]
    return out or list(DEFAULT_SECTIONS)


def _gather_account_export_data(user, *, locale: str = "en", country_code: str = "TZ") -> dict[str, Any]:
    qs = MapFeature.objects.filter(is_active=True, layer__is_active=True)
    stats = build_feature_coverage_stats(qs, country_code=country_code, locale=locale)
    return {
        "mode": "account",
        "title": "Terra Meta Intelligence Brief",
        "subtitle": "Platform-wide mapped mineral coverage",
        "country_code": country_code,
        "generated_at": timezone.now().isoformat(),
        "total_zones": stats.get("total_prospects", 0),
        "total_area_km2": stats.get("total_area_km2"),
        "minerals": stats.get("minerals", [])[:12],
        "regions": stats.get("hotspots", [])[:10],
        "layers": stats.get("layers", [])[:10],
    }


def _gather_map_export_data(
    user,
    *,
    locale: str = "en",
    lat: float | None = None,
    lng: float | None = None,
    zoom: int = 8,
    mineral_slug: str = "",
    region_id: int | None = None,
    layer_id: int | None = None,
    feature_ids: list[int] | None = None,
    boundary_id: int | None = None,
    country_code: str = "TZ",
) -> dict[str, Any]:
    ctx = None
    if layer_id is not None:
        ctx = layer_coverage_context(layer_id, user, locale=locale)
    elif mineral_slug:
        ctx = mineral_coverage_context(mineral_slug, user, locale=locale)
    elif region_id is not None:
        ctx = region_coverage_context(region_id, user, locale=locale)
    elif lat is not None and lng is not None:
        ctx = area_location_context(
            lat,
            lng,
            zoom,
            user,
            locale=locale,
            feature_ids=feature_ids,
            admin_boundary_id=boundary_id,
            country_code=country_code,
        )

    if not ctx:
        return _gather_account_export_data(user, locale=locale, country_code=country_code)

    name = ctx.get("search_name") or ctx.get("region_name") or "Selected area"
    return {
        "mode": "map",
        "title": f"Terra Meta Area Brief - {name}",
        "subtitle": ctx.get("search_type") or "Location analysis",
        "country_code": country_code,
        "generated_at": timezone.now().isoformat(),
        "center": ctx.get("center"),
        "feature_count": ctx.get("feature_count", 0),
        "total_area_km2": ctx.get("total_area_km2"),
        "minerals": ctx.get("minerals", [])[:12],
        "regions": ctx.get("top_regions", [])[:10],
        "ai_context": build_search_ai_context(ctx) if ctx.get("search_name") else build_area_ai_context(ctx),
        "admin": {
            "region": ctx.get("region_name"),
            "district": ctx.get("district_name"),
            "ward": ctx.get("ward_name"),
            "village": ctx.get("village_name"),
        },
    }


def gather_insight_export_data(
    user,
    *,
    mode: str = "account",
    locale: str = "en",
    sections: list[str] | None = None,
    messages: list[dict[str, str]] | None = None,
    **map_kwargs,
) -> dict[str, Any]:
    sections = _normalize_sections(sections)
    if mode == "map":
        data = _gather_map_export_data(user, locale=locale, **map_kwargs)
    else:
        data = _gather_account_export_data(user, locale=locale, country_code=map_kwargs.get("country_code", "TZ"))

    data["sections"] = sections
    data["chat_messages"] = [
        {"role": m["role"], "content": m["content"]}
        for m in (messages or [])
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    return data


def _build_data_context_block(data: dict[str, Any]) -> str:
    lines = [
        f"Report title: {data.get('title')}",
        f"Scope: {data.get('subtitle')}",
        f"Total mapped zones: {data.get('total_zones') or data.get('feature_count') or 0}",
    ]
    area = data.get("total_area_km2")
    if area:
        lines.append(f"Total polygon coverage area: {area:.2f} km²")

    admin = data.get("admin") or {}
    hierarchy = [admin.get("region"), admin.get("district"), admin.get("ward"), admin.get("village")]
    hierarchy = [h for h in hierarchy if h]
    if hierarchy:
        lines.append(f"Administrative location: {' · '.join(hierarchy)}")

    minerals = data.get("minerals") or []
    if minerals:
        lines.append("Minerals:")
        for m in minerals[:10]:
            line = f"- {m.get('name', m.get('slug', ''))}: {m.get('count', m.get('feature_count', 0))} zones"
            if m.get("area_km2"):
                line += f", {m['area_km2']:.2f} km²"
            lines.append(line)

    regions = data.get("regions") or []
    if regions:
        lines.append("Regions:")
        for r in regions[:10]:
            name = r.get("region") or r.get("name") or "Unknown"
            count = r.get("feature_count") or r.get("count") or 0
            line = f"- {name}: {count} zones"
            if r.get("area_km2"):
                line += f", {r['area_km2']:.2f} km²"
            lines.append(line)

    layers = data.get("layers") or []
    if layers:
        lines.append("Top layers:")
        for layer in layers[:8]:
            lines.append(
                f"- {layer.get('name')}: {layer.get('feature_count', 0)} features ({layer.get('layer_type', '')})"
            )

    return "\n".join(lines)


def _summarize_chat(messages: list[dict[str, str]]) -> str:
    if not messages:
        return ""
    lines = ["Conversation highlights:"]
    for msg in messages[-12:]:
        role = "User" if msg.get("role") == "user" else "Terra"
        content = (msg.get("content") or "").strip().replace("\n", " ")
        if len(content) > 400:
            content = content[:400].rsplit(" ", 1)[0] + "…"
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def generate_export_narrative(data: dict[str, Any]) -> tuple[str, str]:
    context = _build_data_context_block(data)
    if "chat" in data.get("sections", []) and data.get("chat_messages"):
        context = f"{context}\n\n{_summarize_chat(data['chat_messages'])}"
    prompt = f"{EXPORT_NARRATIVE_PROMPT}\n\nDATA:\n{context}"
    return generate_map_insight(prompt)


def _simple_bar_table(labels: list[str], values: list[int], header: str) -> Table | None:
    if not labels or not values:
        return None
    max_val = max(values) or 1
    rows = [[header, "Zones", ""]]
    for label, value in zip(labels[:8], values[:8]):
        bar_len = max(1, int(20 * value / max_val))
        rows.append([label, str(value), "█" * bar_len])
    table = Table(rows, colWidths=[2.4 * inch, 0.7 * inch, 2.6 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#166534")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TEXTCOLOR", (2, 1), (2, -1), colors.HexColor("#0d9488")),
            ]
        )
    )
    return table


def _minerals_table(minerals: list[dict]) -> Table | None:
    if not minerals:
        return None
    rows = [["Mineral", "Zones", "Area (km²)"]]
    for m in minerals[:12]:
        rows.append(
            [
                str(m.get("name") or m.get("slug") or ""),
                str(m.get("count") or m.get("feature_count") or 0),
                f"{m['area_km2']:.2f}" if m.get("area_km2") else "-",
            ]
        )
    table = Table(rows, colWidths=[2.5 * inch, 1.0 * inch, 1.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    return table


def build_insight_export_pdf(
    data: dict[str, Any],
    *,
    narrative: str = "",
    map_snapshot: bytes | None = None,
) -> bytes:
    sections = data.get("sections") or list(DEFAULT_SECTIONS)
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
        title=data.get("title") or "Terra Meta Report",
        author="Terra Meta · 5G Geology",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExportTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "ExportSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#475569"),
        spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "ExportSection",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#166534"),
        spaceBefore=14,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ExportBody",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "ExportMeta",
        parent=styles["Normal"],
        fontSize=8.5,
        textColor=colors.HexColor("#64748b"),
    )

    story: list = []
    story.append(_wrap_text(data.get("title") or "Terra Meta Intelligence Brief", title_style))
    story.append(_wrap_text(data.get("subtitle") or "", subtitle_style))
    generated = data.get("generated_at")
    try:
        when = datetime.fromisoformat(str(generated)).strftime("%d %B %Y %H:%M UTC")
    except (TypeError, ValueError):
        when = timezone.now().strftime("%d %B %Y")
    story.append(_wrap_text(f"Generated {when} · Terra Meta Mineral Intelligence", meta_style))
    story.append(Spacer(1, 0.15 * inch))

    if "overview" in sections and narrative:
        story.append(_wrap_text("Executive narrative", section_style))
        for block in narrative.split("\n\n"):
            chunk = block.strip()
            if chunk:
                story.append(_wrap_text(chunk, body_style))

    if "analytics" in sections:
        story.append(_wrap_text("Coverage snapshot", section_style))
        zones = data.get("total_zones") or data.get("feature_count") or 0
        area = data.get("total_area_km2")
        summary = f"Mapped prospect zones in scope: {zones:,}."
        if area:
            summary += f" Total polygon coverage: {area:,.2f} km²."
        story.append(_wrap_text(summary, body_style))

    if "minerals" in sections:
        minerals = data.get("minerals") or []
        if minerals:
            story.append(_wrap_text("Mineral breakdown", section_style))
            table = _minerals_table(minerals)
            if table:
                story.append(table)
                story.append(Spacer(1, 0.12 * inch))

    if "regions" in sections:
        regions = data.get("regions") or []
        if regions:
            story.append(_wrap_text("Regional distribution", section_style))
            labels = [str(r.get("region") or r.get("name") or "") for r in regions]
            values = [int(r.get("feature_count") or r.get("count") or 0) for r in regions]
            chart = _simple_bar_table(labels, values, "Region")
            if chart:
                story.append(chart)
                story.append(Spacer(1, 0.12 * inch))

    if "chat" in sections and data.get("chat_messages"):
        story.append(_wrap_text("Ask Terra conversation", section_style))
        for msg in data["chat_messages"][-10:]:
            role = "You" if msg.get("role") == "user" else "Terra"
            content = (msg.get("content") or "").strip()
            if content:
                story.append(_wrap_text(f"{role}: {content}", body_style))

    if "map_snapshot" in sections and map_snapshot:
        story.append(_wrap_text("Map snapshot", section_style))
        try:
            img = Image(ImageReader(io.BytesIO(map_snapshot)), width=6.2 * inch, height=4.0 * inch)
            story.append(img)
            story.append(Spacer(1, 0.1 * inch))
        except Exception:
            story.append(_wrap_text("Map snapshot could not be embedded.", meta_style))

    story.append(Spacer(1, 0.2 * inch))
    story.append(
        _wrap_text(
            "This report was generated by Terra Meta from mapped platform data and your selected insights. "
            "It supports exploration planning and due diligence; verify critical decisions with licensed survey and field work.",
            meta_style,
        )
    )

    def _draw_page(canvas, doc_template):
        canvas.saveState()
        left = doc.leftMargin
        right = A4[0] - doc.rightMargin
        page_top = A4[1]
        if wordmark_path:
            canvas.drawImage(
                str(wordmark_path),
                left,
                page_top - doc.topMargin + 0.18 * inch,
                width=2.2 * inch,
                height=0.48 * inch,
                preserveAspectRatio=True,
                mask="auto",
            )
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(left, 0.42 * inch, "Terra Meta · Insight Export")
        page_label = f"Page {doc_template.page}"
        if icon_path:
            icon_size = 0.38 * inch
            icon_x = right - icon_size
            canvas.drawImage(
                str(icon_path),
                icon_x,
                0.36 * inch,
                width=icon_size,
                height=icon_size,
                preserveAspectRatio=True,
                mask="auto",
            )
            canvas.drawRightString(icon_x - 0.1 * inch, 0.42 * inch, page_label)
        else:
            canvas.drawRightString(right, 0.42 * inch, page_label)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return buffer.getvalue()


def build_insight_export_for_user(
    user,
    *,
    mode: str = "account",
    locale: str = "en",
    sections: list[str] | None = None,
    messages: list[dict[str, str]] | None = None,
    map_snapshot_b64: str | None = None,
    include_narrative: bool = True,
    **map_kwargs,
) -> bytes:
    if not user_has_map_detail_access(user):
        raise PermissionError("Subscription required for insight exports.")

    data = gather_insight_export_data(
        user,
        mode=mode,
        locale=locale,
        sections=sections,
        messages=messages,
        **map_kwargs,
    )
    narrative = ""
    if include_narrative and "overview" in data.get("sections", []):
        raw, _model = generate_export_narrative(data)
        narrative = sanitize_assistant_output(raw)

    snapshot = _decode_map_snapshot(map_snapshot_b64)
    return build_insight_export_pdf(data, narrative=narrative, map_snapshot=snapshot)
