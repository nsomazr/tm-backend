"""Build Terra insight export PDFs for paid subscribers (Ask Terra report mode)."""

from __future__ import annotations

import base64
import io
import logging
import re
from datetime import datetime
from typing import Any

from django.utils import timezone
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.maps.access import user_has_map_detail_access
from apps.maps.models import MapFeature
from apps.reports.ai_service import generate_export_narrative_text, sanitize_report_text
from apps.reports.pdf_service import _brand_logo_path, _wordmark_path

from .map_snapshot_server import generate_server_map_snapshot
from .coverage_stats import build_feature_coverage_stats
from .insights import (
    area_location_context,
    build_area_ai_context,
    build_search_ai_context,
    generate_basic_map_insight,
    layer_coverage_context,
    mineral_coverage_context,
    region_coverage_context,
)

DEFAULT_SECTIONS = ("overview", "minerals", "regions", "analytics", "map_snapshot")

logger = logging.getLogger(__name__)

_SCOPE_LABELS = {
    "analysis_zone": "Circular analysis area around selected point",
    "reference_buffer": "Mapped reference areas linked to this location",
    "exploration_area": "User-drawn exploration geometry",
    "admin_boundary": "Administrative boundary search",
}

_SEARCH_TYPE_LABELS = {
    "mineral": "Mineral search",
    "region": "Regional search",
    "layer": "Layer search",
    "region_boundary": "Regional boundary analysis",
    "district_boundary": "District boundary analysis",
    "ward_boundary": "Ward boundary analysis",
    "village_boundary": "Village boundary analysis",
}

_NARRATIVE_REJECT_PHRASES = (
    "mental health",
    "physical health",
    "wellness",
    "well-being",
    "fitness",
    "medical",
    "healthcare",
    "hospital",
    "terra data solutions",
    "country of terra",
    "potassium iodide",
    "developed by terra",
    "comprehensive mineral intelligence report developed",
    "1 million square",
)

_COUNTRY_NAMES = {
    "TZ": "Tanzania",
    "KE": "Kenya",
    "UG": "Uganda",
}


def _admin_from_context(ctx: dict[str, Any]) -> dict[str, str | None]:
    region_info = ctx.get("region_boundary") or {}
    district_info = ctx.get("district_boundary") or {}
    ward_info = ctx.get("ward_boundary") or {}
    village_info = ctx.get("village_boundary") or {}
    geographic = ctx.get("geographic_region") or ctx.get("region")
    return {
        "region": region_info.get("name") or geographic,
        "district": district_info.get("name"),
        "ward": ward_info.get("name"),
        "village": village_info.get("name"),
    }


def _location_display_name(data: dict[str, Any]) -> str:
    admin = data.get("admin") or {}
    for key in ("village", "ward", "district", "region"):
        name = admin.get(key)
        if name:
            return str(name)
    if data.get("location_name"):
        return str(data["location_name"])
    if data.get("geographic_region"):
        return str(data["geographic_region"])
    lat = data.get("lat")
    lng = data.get("lng")
    center = data.get("center") or {}
    if lat is None:
        lat = center.get("lat")
    if lng is None:
        lng = center.get("lng")
    if lat is not None and lng is not None:
        return f"{float(lat):.4f}°N, {float(lng):.4f}°E".replace("°N, -", "°S, ").replace("°E", "°E")
    return "Selected area"


def _country_display_name(data: dict[str, Any]) -> str:
    code = str(data.get("country_code") or "TZ").upper()
    return _COUNTRY_NAMES.get(code, code)


def _admin_hierarchy_text(data: dict[str, Any]) -> str:
    admin = data.get("admin") or {}
    parts = [admin.get("region"), admin.get("district"), admin.get("ward"), admin.get("village")]
    parts = [p for p in parts if p]
    return " · ".join(parts)


def _humanize_scope(scope: str | None) -> str:
    if not scope:
        return ""
    key = str(scope).strip().lower()
    return _SCOPE_LABELS.get(key, key.replace("_", " ").strip().title())


def _export_subtitle(ctx: dict[str, Any], *, exploration_geometry: dict | None = None) -> str:
    if exploration_geometry:
        return "User-drawn exploration"
    search_type = ctx.get("search_type")
    if search_type:
        key = str(search_type).strip().lower()
        return _SEARCH_TYPE_LABELS.get(key, key.replace("_", " ").title())
    scope = ctx.get("insight_scope")
    if scope:
        return _humanize_scope(str(scope))
    return "Location analysis"


MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_DIMENSION = 4096


def _decode_map_snapshot(raw: str | None) -> bytes | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    match = re.match(r"data:image/(?:png|jpeg|jpg|webp);base64,(.+)", text, re.DOTALL | re.IGNORECASE)
    payload = match.group(1) if match else text
    payload = re.sub(r"\s+", "", payload)
    try:
        data = base64.b64decode(payload, validate=False)
        if not data or len(data) > MAX_SNAPSHOT_BYTES:
            return None
        try:
            return _prepare_snapshot_bytes(data)
        except Exception:
            return None
    except Exception:
        return None


def _prepare_snapshot_bytes(raw: bytes) -> bytes:
    """Normalize browser canvas exports for ReportLab embedding."""
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot too large")
    with PILImage.open(io.BytesIO(raw)) as img:
        width, height = img.size
        if width > MAX_SNAPSHOT_DIMENSION or height > MAX_SNAPSHOT_DIMENSION:
            raise ValueError("Snapshot dimensions too large")
        if width * height > MAX_SNAPSHOT_DIMENSION * MAX_SNAPSHOT_DIMENSION:
            raise ValueError("Snapshot pixel count too large")
        if img.mode in ("RGBA", "LA", "P"):
            background = PILImage.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            alpha = img.split()[-1] if img.mode in ("RGBA", "LA") else None
            background.paste(img, mask=alpha)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()


def _frame_snapshot_for_pdf(raw: bytes) -> bytes:
    """Add top breathing room and a single rounded teal border around the figure."""
    from PIL import ImageDraw

    prepared = _prepare_snapshot_bytes(raw)
    with PILImage.open(io.BytesIO(prepared)) as img:
        img = img.convert("RGB")
        w, h = img.size
        margin_top = 32
        margin_sides = 24
        margin_bottom = 20
        inset_pad = 14
        border = 3
        radius = 20
        out_w = w + margin_sides * 2 + inset_pad * 2
        out_h = h + margin_top + margin_bottom + inset_pad * 2
        canvas = PILImage.new("RGB", (out_w, out_h), (255, 255, 255))
        paste_x = margin_sides + inset_pad
        paste_y = margin_top + inset_pad
        canvas.paste(img, (paste_x, paste_y))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            [margin_sides, margin_top, out_w - margin_sides, out_h - margin_bottom],
            radius=radius,
            outline=(13, 148, 136),
            width=border,
        )
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()


def _wrap_text(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(safe, style)


def _inline_markdown_markup(text: str) -> str:
    safe = (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", safe)
    safe = re.sub(r"`(.+?)`", r'<font name="Courier" size="9">\1</font>', safe)
    return safe


def _resolve_map_snapshot(
    map_snapshot: bytes | None,
    data: dict[str, Any],
    *,
    user=None,
) -> bytes | None:
    if map_snapshot:
        try:
            return _prepare_snapshot_bytes(map_snapshot)
        except Exception as exc:
            logger.warning("Client map snapshot invalid, trying server fallback: %s", exc)

    if "map_snapshot" not in (data.get("sections") or []):
        return None

    lat = data.get("lat")
    lng = data.get("lng")
    center = data.get("center") or {}
    if lat is None:
        lat = center.get("lat")
    if lng is None:
        lng = center.get("lng")
    if lat is None or lng is None:
        return None

    return generate_server_map_snapshot(
        float(lat),
        float(lng),
        analysis_area_km2=data.get("analysis_area_km2"),
        country_code=str(data.get("country_code") or "TZ"),
        user=user,
        feature_ids=data.get("feature_ids"),
        zoom=int(data.get("zoom") or 12),
    )


def _snapshot_image(map_snapshot: bytes, *, max_width: float, max_height: float) -> Image:
    prepared = _frame_snapshot_for_pdf(map_snapshot)
    with PILImage.open(io.BytesIO(prepared)) as img:
        iw, ih = img.size
    if not iw or not ih:
        raise ValueError("invalid snapshot dimensions")
    scale = min(max_width / iw, max_height / ih)
    return Image(io.BytesIO(prepared), width=iw * scale, height=ih * scale)


def _is_section_heading(line: str) -> bool:
    text = line.strip()
    if not text or len(text) >= 80 or text.endswith("."):
        return False
    if re.match(r"^\d+\.\s", text):
        return False
    if re.match(r"^[-*•]\s", text):
        return False
    if re.match(r"^#{1,6}\s", text):
        return True
    known = {
        "executive summary",
        "mineral coverage",
        "minerals covered",
        "regional distribution",
        "analysis and trends",
        "recommendations",
        "key findings",
        "coverage snapshot",
    }
    if text.lower() in known:
        return True
    words = text.split()
    if len(words) < 2 or len(words) > 8:
        return False
    return all(w[:1].isupper() for w in words if w)


def _append_location_summary(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    body_style: ParagraphStyle,
    meta_style: ParagraphStyle,
) -> None:
    admin = data.get("admin") or {}
    hierarchy = _admin_hierarchy_text(data)
    center = data.get("center") or {}
    lat = data.get("lat") or center.get("lat")
    lng = data.get("lng") or center.get("lng")
    analysis_km2 = data.get("analysis_area_km2")
    scope = data.get("insight_scope")
    feature_count = data.get("feature_count") or data.get("total_zones") or 0

    if not hierarchy and lat is None and lng is None and not analysis_km2:
        return

    story.append(_wrap_text("Location summary", section_style))
    story.append(
        Paragraph(
            f"<b>Area:</b> {_inline_markdown_markup(_location_display_name(data))}",
            body_style,
        )
    )
    hierarchy = _admin_hierarchy_text(data)
    if hierarchy:
        story.append(
            Paragraph(
                f"<b>Administrative area:</b> {_inline_markdown_markup(hierarchy)}",
                body_style,
            )
        )
    story.append(
        Paragraph(
            f"<b>Country:</b> {_country_display_name(data)}",
            body_style,
        )
    )
    if lat is not None and lng is not None:
        story.append(
            Paragraph(
                f"<b>Coordinates:</b> {float(lat):.5f}, {float(lng):.5f}",
                body_style,
            )
        )
    if analysis_km2:
        story.append(
            Paragraph(
                f"<b>Analysis area:</b> ~{float(analysis_km2):,.2f} km² circular search area",
                body_style,
            )
        )
    if scope:
        story.append(
            Paragraph(
                f"<b>Scope:</b> {_inline_markdown_markup(_humanize_scope(str(scope)))}",
                body_style,
            )
        )
    if feature_count:
        story.append(
            Paragraph(
                f"<b>Mapped areas in scope:</b> {int(feature_count):,}",
                body_style,
            )
        )
    if data.get("exploration_geometry"):
        geom = data["exploration_geometry"]
        story.append(
            Paragraph(
                f"<b>Exploration geometry:</b> user-drawn {geom.get('type', 'area')} on the map",
                body_style,
            )
        )
    story.append(Spacer(1, 0.1 * inch))


def _build_fallback_narrative(data: dict[str, Any]) -> str:
    parts: list[str] = []
    title = data.get("title") or "Selected area"
    zones = data.get("feature_count") or data.get("total_zones") or 0
    area = data.get("total_area_km2")
    intro = f"This brief summarizes mineral intelligence for {title}."
    if zones:
        intro += f" The analysis covers {zones:,} mapped prospect areas"
        if area:
            intro += f" spanning approximately {area:,.2f} km² of mineral coverage"
        intro += "."
    parts.append(intro)

    minerals = data.get("minerals") or []
    if minerals:
        top = minerals[:5]
        mineral_bits = [
            f"{m.get('name') or m.get('slug')} ({m.get('count') or m.get('feature_count', 0)} areas)"
            for m in top
        ]
        parts.append(f"Leading minerals in scope include {', '.join(mineral_bits)}.")

    regions = data.get("regions") or []
    if regions:
        region_bits = [
            f"{r.get('region') or r.get('name')} ({r.get('feature_count') or r.get('count', 0)} areas)"
            for r in regions[:5]
        ]
        parts.append(f"Regional concentration is strongest in {', '.join(region_bits)}.")

    admin = data.get("admin") or {}
    hierarchy = [admin.get("region"), admin.get("district"), admin.get("ward"), admin.get("village")]
    hierarchy = [h for h in hierarchy if h]
    if hierarchy:
        parts.append(f"The selected point lies within {' · '.join(hierarchy)}.")

    return "\n\n".join(parts)


def _narrative_looks_valid(narrative: str, data: dict[str, Any]) -> bool:
    text = (narrative or "").strip()
    if len(text.split()) < 50:
        return False
    lower = text.lower()
    if any(phrase in lower for phrase in _NARRATIVE_REJECT_PHRASES):
        return False
    if "terra meta" in lower and "area brief" not in lower and data.get("mode") == "map":
        return False
    location = _location_display_name(data).lower()
    if location != "selected area" and location not in lower:
        hierarchy = _admin_hierarchy_text(data).lower()
        if hierarchy and not any(part.lower() in lower for part in hierarchy.split(" · ") if part):
            return False
    minerals = data.get("minerals") or []
    if minerals:
        names = [str(m.get("name") or m.get("slug") or "").lower() for m in minerals[:6]]
        names = [n for n in names if n]
        if names and not any(name in lower for name in names):
            return False
    country = _country_display_name(data).lower()
    if country and country not in lower and data.get("mode") == "map":
        return False
    return True


def _append_structured_overview(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    subsection_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    location = _location_display_name(data)
    country = _country_display_name(data)
    hierarchy = _admin_hierarchy_text(data)
    zones = int(data.get("feature_count") or data.get("total_zones") or 0)
    area = data.get("total_area_km2")
    analysis_km2 = data.get("analysis_area_km2")
    lat = data.get("lat")
    lng = data.get("lng")
    center = data.get("center") or {}
    if lat is None:
        lat = center.get("lat")
    if lng is None:
        lng = center.get("lng")
    scope = _humanize_scope(str(data.get("insight_scope") or ""))
    minerals = data.get("minerals") or []
    sections = data.get("sections") or []
    labels = data.get("labels") or []

    story.append(Paragraph("Executive Summary", section_style))
    lead = f"This geological exploration brief focuses on <b>{_inline_markdown_markup(location)}</b>"
    if hierarchy:
        lead += f" ({_inline_markdown_markup(hierarchy)}, {country})"
    else:
        lead += f" in {country}"
    lead += "."
    story.append(Paragraph(lead, body_style))

    if lat is not None and lng is not None:
        coord_line = f"Analysis coordinates: <b>{float(lat):.5f}, {float(lng):.5f}</b>"
        if analysis_km2:
            coord_line += f" · search area ~<b>{float(analysis_km2):,.0f} km²</b>"
        if scope:
            coord_line += f" · {_inline_markdown_markup(scope)}"
        story.append(Paragraph(coord_line + ".", body_style))

    if zones:
        zone_line = (
            f"Terra Meta maps <b>{zones:,}</b> mineral prospect area{'s' if zones != 1 else ''} "
            f"in this area"
        )
        if area:
            zone_line += f", with <b>{float(area):,.2f} km²</b> of combined mapped mineral coverage"
        zone_line += "."
        story.append(Paragraph(zone_line, body_style))
    else:
        story.append(
            Paragraph(
                "No mapped prospect areas were found in this search area. "
                "Use this brief for location context and widen the analysis area if needed.",
                body_style,
            )
        )
    story.append(Spacer(1, 0.08 * inch))

    if minerals:
        story.append(Paragraph("Minerals in this area", section_style))
        if "minerals" in sections and len(minerals) == 1:
            top = minerals[0]
            name = top.get("name") or top.get("slug") or "Unknown"
            count = int(top.get("count") or top.get("feature_count") or 0)
            m_area = top.get("area_km2")
            line = (
                f"<b>{_inline_markdown_markup(str(name))}</b> is the mapped commodity here "
                f"({count:,} area{'s' if count != 1 else ''}"
            )
            if m_area:
                line += f", {float(m_area):,.2f} km² mineral coverage"
            line += "). See the breakdown table below for detail."
            story.append(Paragraph(line, body_style))
        else:
            for mineral in minerals[:8]:
                name = mineral.get("name") or mineral.get("slug") or "Unknown"
                count = int(mineral.get("count") or mineral.get("feature_count") or 0)
                m_area = mineral.get("area_km2")
                detail = f"{count:,} mapped feature{'s' if count != 1 else ''}"
                occ = int(mineral.get("occurrence_count") or 0)
                poly = int(mineral.get("polygon_count") or 0)
                if occ or poly:
                    parts = []
                    if occ:
                        parts.append(f"{occ:,} point occurrence{'s' if occ != 1 else ''}")
                    if poly:
                        parts.append(f"{poly:,} polygon area{'s' if poly != 1 else ''}")
                    detail = ", ".join(parts)
                if m_area:
                    detail += f", {float(m_area):,.2f} km²"
                story.append(Paragraph(f"<b>{_inline_markdown_markup(str(name))}</b>", subsection_style))
                story.append(
                    Paragraph(
                        f"Mapped evidence near {location}: {detail}. "
                        f"Follow up with license checks, geophysics/geochem, and field mapping.",
                        body_style,
                    )
                )
        story.append(Spacer(1, 0.06 * inch))
    elif labels:
        story.append(Paragraph("Mapped features", section_style))
        story.append(
            Paragraph(
                f"Mapped area labels near {location}: {_inline_markdown_markup(', '.join(labels[:6]))}.",
                body_style,
            )
        )
        story.append(Spacer(1, 0.06 * inch))

    regions = data.get("regions") or []
    if regions:
        story.append(Paragraph("Regional geological context", section_style))
        bits = []
        for region in regions[:6]:
            name = region.get("region") or region.get("name") or "Unknown"
            count = int(region.get("feature_count") or region.get("count") or 0)
            r_area = region.get("area_km2")
            bit = f"<b>{_inline_markdown_markup(str(name))}</b> ({count:,} areas"
            if r_area:
                bit += f", {float(r_area):,.2f} km²"
            bit += ")"
            bits.append(bit)
        story.append(
            Paragraph(
                f"Within {country}, activity near {location} relates to: " + "; ".join(bits) + ".",
                body_style,
            )
        )
        story.append(Spacer(1, 0.06 * inch))

    story.append(Paragraph("Exploration recommendations", section_style))
    if zones <= 2 and minerals:
        primary = minerals[0].get("name") or minerals[0].get("slug") or "the mapped commodity"
        story.append(
            Paragraph(
                f"Limited coverage at {location} still indicates <b>{_inline_markdown_markup(str(primary))}</b>. "
                f"Prioritise ground truthing, sampling, and cadastre review before drill commitments.",
                body_style,
            )
        )
    elif zones <= 2:
        story.append(
            Paragraph(
                f"Sparse mapping at {location}. Expand the search radius and commission licensed "
                f"geological survey before exploration commitments.",
                body_style,
            )
        )
    else:
        story.append(
            Paragraph(
                f"Use this brief to rank targets around {location}, verify licenses and environmental "
                f"constraints, then validate with field geology and sampling.",
                body_style,
            )
        )
    story.append(Spacer(1, 0.1 * inch))


def _append_site_assessment(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    text = (data.get("site_assessment") or "").strip()
    if not text:
        return
    story.append(Paragraph("Site assessment", section_style))
    for paragraph in re.split(r"\n\s*\n", text):
        chunk = paragraph.strip()
        if not chunk:
            continue
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            bullet = re.match(r"^[-*•]\s+(.+)$", line)
            if bullet:
                story.append(Paragraph(f"• {_inline_markdown_markup(bullet.group(1))}", body_style))
            else:
                story.append(Paragraph(_inline_markdown_markup(line), body_style))
    story.append(Spacer(1, 0.08 * inch))


def _append_location_analysis(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    location = _location_display_name(data)
    country = _country_display_name(data)
    hierarchy = _admin_hierarchy_text(data)
    lat = data.get("lat")
    lng = data.get("lng")
    center = data.get("center") or {}
    if lat is None:
        lat = center.get("lat")
    if lng is None:
        lng = center.get("lng")
    geo = data.get("geographic_region") or data.get("location_name")

    story.append(Paragraph("Location analysis", section_style))
    intro = (
        f"The study area centres on <b>{_inline_markdown_markup(location)}</b> in <b>{country}</b>"
    )
    if hierarchy:
        intro += f", within the administrative hierarchy {_inline_markdown_markup(hierarchy)}"
    intro += "."
    story.append(Paragraph(intro, body_style))

    if geo and str(geo).lower() != str(location).lower():
        story.append(
            Paragraph(
                f"Regional context: {_inline_markdown_markup(str(geo))} is the broader geological "
                f"and administrative frame for licence, infrastructure, and tenure review.",
                body_style,
            )
        )
    if lat is not None and lng is not None:
        story.append(
            Paragraph(
                f"Map reference point: {float(lat):.5f}°N, {float(lng):.5f}°E "
                f"(WGS84). Use these coordinates for GIS overlays and cadastre checks.",
                body_style,
            )
        )
    direction = data.get("direction_insights") or {}
    direction_lines = direction.get("summary_lines") or []
    if direction_lines:
        story.append(Paragraph("Compass distribution", body_style))
        for line in direction_lines:
            story.append(Paragraph(_inline_markdown_markup(line), body_style))
    structure = data.get("structure_orientations") or {}
    structure_lines = structure.get("summary_lines") or []
    if structure_lines:
        story.append(Paragraph("Structural trends", body_style))
        for line in structure_lines:
            story.append(Paragraph(_inline_markdown_markup(line), body_style))
    refs = data.get("reference_buffers") or []
    if refs:
        story.append(Paragraph("Reference buffer context:", body_style))
        for ref in refs[:4]:
            story.append(
                Paragraph(
                    f"• {_inline_markdown_markup(ref.get('layer_name') or 'Layer')}: "
                    f"{ref.get('buffer_km', '?')} km buffer around "
                    f"{_inline_markdown_markup(str(ref.get('anchor_label') or 'anchor feature'))}.",
                    body_style,
                )
            )
    story.append(Spacer(1, 0.08 * inch))


def _append_geological_interpretation(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    body_style: ParagraphStyle,
    subsection_style: ParagraphStyle,
) -> None:
    minerals = data.get("minerals") or []
    zones = int(data.get("feature_count") or data.get("total_zones") or 0)
    area = data.get("total_area_km2")
    location = _location_display_name(data)
    country = _country_display_name(data)

    story.append(Paragraph("Geological interpretation", section_style))
    if not minerals and zones == 0:
        story.append(
            Paragraph(
                f"No published mapped mineral features were identified within the analysis "
                f"area at {location}. This does not exclude mineralisation; it indicates that Terra Meta "
                f"layers do not yet cover this exact ground. Wider regional mapping and archival "
                f"literature should be consulted before field programmes.",
                body_style,
            )
        )
        story.append(Spacer(1, 0.08 * inch))
        return

    story.append(
        Paragraph(
            f"Mapped coverage near {location} indicates <b>{zones:,}</b> prospect area"
            f"{'s' if zones != 1 else ''} across <b>{len(minerals)}</b> commodity "
            f"type{'s' if len(minerals) != 1 else ''} in {country}."
            + (
                f" Combined mineral footprint is approximately <b>{float(area):,.2f} km²</b>."
                if area
                else ""
            ),
            body_style,
        )
    )
    for mineral in minerals[:6]:
        name = mineral.get("name") or mineral.get("slug") or "Unknown"
        count = int(mineral.get("count") or mineral.get("feature_count") or 0)
        m_area = mineral.get("area_km2")
        story.append(Paragraph(f"<b>{_inline_markdown_markup(str(name))}</b>", subsection_style))
        occ = int(mineral.get("occurrence_count") or 0)
        poly = int(mineral.get("polygon_count") or 0)
        if occ or poly:
            bits = []
            if occ:
                bits.append(
                    f"{occ:,} point occurrence{'s' if occ != 1 else ''}"
                )
            if poly:
                bits.append(f"{poly:,} polygon area{'s' if poly != 1 else ''}")
            detail = " and ".join(bits) + " fall within the analysis scope"
        else:
            detail = (
                f"{count:,} mapped feature{'s' if count != 1 else ''} fall within the analysis scope"
            )
        if m_area:
            detail += f", covering roughly {float(m_area):,.2f} km² of mapped mineral area"
        detail += (
            ". Point occurrences are discrete mapped locations; polygon areas are exploration "
            "indicators from published or platform-managed layers, not resource estimates. "
            "Structural controls, alteration, and host lithology should be confirmed in the field."
        )
        story.append(Paragraph(detail + ".", body_style))
    story.append(Spacer(1, 0.08 * inch))


def _append_zone_inventory(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    labels = [str(label).strip() for label in (data.get("labels") or []) if str(label).strip()]
    if not labels:
        return
    story.append(Paragraph("Mapped area inventory", section_style))
    rows = [["#", "Area label"]]
    for index, label in enumerate(labels[:12], start=1):
        rows.append([str(index), label])
    table = Table(rows, colWidths=[0.45 * inch, 5.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)
    story.append(
        Paragraph(
            "Labels are taken from active mapped features inside the analysis scope. "
            "Cross-check names against licence registers and field maps.",
            body_style,
        )
    )
    story.append(Spacer(1, 0.08 * inch))


def _append_key_findings(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    findings: list[str] = []
    location = _location_display_name(data)
    zones = int(data.get("feature_count") or data.get("total_zones") or 0)
    minerals = data.get("minerals") or []
    analysis_km2 = data.get("analysis_area_km2")
    scope = _humanize_scope(str(data.get("insight_scope") or ""))

    if analysis_km2:
        findings.append(
            f"Analysis covers a circular area of approximately {float(analysis_km2):,.0f} km² "
            f"centred on {location}."
        )
    if scope:
        findings.append(f"Insight scope: {scope}.")
    if zones:
        findings.append(f"{zones:,} mapped mineral areas intersect the analysis area.")
    else:
        findings.append("No mapped mineral areas were found in the current analysis scope.")
    for mineral in minerals[:5]:
        name = mineral.get("name") or mineral.get("slug") or "Unknown"
        count = int(mineral.get("count") or 0)
        line = f"{name}: {count} mapped area{'s' if count != 1 else ''}"
        if mineral.get("area_km2"):
            line += f", {float(mineral['area_km2']):,.2f} km² mineral coverage"
        findings.append(line + ".")
    regions = data.get("regions") or data.get("top_regions") or []
    if regions:
        top = regions[0]
        rname = top.get("region") or top.get("name") or "Unknown"
        rcount = int(top.get("feature_count") or top.get("count") or 0)
        findings.append(f"Highest regional concentration: {rname} ({rcount} areas).")
    findings.append(
        "Validate all mapped indicators with licence status, environmental constraints, "
        "and field geological work before investment decisions."
    )

    story.append(Paragraph("Key findings", section_style))
    for item in findings[:10]:
        story.append(Paragraph(f"• {_inline_markdown_markup(item)}", body_style))
    story.append(Spacer(1, 0.08 * inch))


def _append_methodology_and_data(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    body_style: ParagraphStyle,
    meta_style: ParagraphStyle,
) -> None:
    story.append(Paragraph("Methodology and data sources", section_style))
    story.append(
        Paragraph(
            "This report is generated from Terra Meta's curated mineral mapping layers, "
            "administrative boundary data, and the user's selected map location or exploration "
            "geometry. Mineral minerals, and structures are aggregated within the "
            "defined analysis area using platform spatial rules (including reference buffers where "
            "configured on source layers).",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "Mapped area counts and mineral areas are derived from active features in the database "
            "at export time. The map snapshot shows regional context and a magnified view of the "
            "analysis area with mapped features overlaid where available.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "<b>Limitations:</b> This document supports exploration planning and desktop due "
            "diligence only. It is not a JORC/NI 43-101 resource statement, feasibility study, or "
            "legal title opinion. Reserves, grades, and economic viability are not inferred.",
            body_style,
        )
    )
    generated = data.get("generated_at")
    if generated:
        story.append(Paragraph(f"Data snapshot: {_inline_markdown_markup(str(generated))}.", meta_style))
    story.append(Spacer(1, 0.08 * inch))


def _append_comprehensive_map_report(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    subsection_style: ParagraphStyle,
    body_style: ParagraphStyle,
    meta_style: ParagraphStyle,
) -> None:
    """Admin-style multi-section brief for map location exports."""
    _append_site_assessment(story, data, section_style=section_style, body_style=body_style)
    _append_location_analysis(story, data, section_style=section_style, body_style=body_style)
    _append_geological_interpretation(
        story,
        data,
        section_style=section_style,
        body_style=body_style,
        subsection_style=subsection_style,
    )
    _append_zone_inventory(story, data, section_style=section_style, body_style=body_style)
    _append_key_findings(story, data, section_style=section_style, body_style=body_style)
    _append_methodology_and_data(
        story,
        data,
        section_style=section_style,
        body_style=body_style,
        meta_style=meta_style,
    )


def _append_markdown_narrative(
    story: list,
    narrative: str,
    *,
    section_style: ParagraphStyle,
    subsection_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    for block in re.split(r"\n\s*\n", narrative.strip()):
        chunk = block.strip()
        if not chunk:
            continue
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        first = lines[0]
        heading = re.match(r"^#{1,6}\s+(.+)$", first)
        if heading:
            level = len(first) - len(first.lstrip("#"))
            style = section_style if level <= 3 else subsection_style
            story.append(Paragraph(_inline_markdown_markup(heading.group(1)), style))
            body_lines = lines[1:]
        elif _is_section_heading(first):
            story.append(Paragraph(_inline_markdown_markup(first.lstrip("#").strip()), section_style))
            body_lines = lines[1:]
        else:
            body_lines = lines
        for line in body_lines:
            bullet = re.match(r"^[-*•]\s+(.+)$", line)
            numbered = re.match(r"^(\d+)\.\s+(.+)$", line)
            if bullet:
                story.append(Paragraph(f"• {_inline_markdown_markup(bullet.group(1))}", body_style))
            elif numbered:
                story.append(
                    Paragraph(
                        f"{numbered.group(1)}. {_inline_markdown_markup(numbered.group(2))}",
                        body_style,
                    )
                )
            else:
                story.append(Paragraph(_inline_markdown_markup(line), body_style))
        story.append(Spacer(1, 0.06 * inch))


def _append_chat_messages(
    story: list,
    messages: list[dict[str, str]],
    *,
    section_style: ParagraphStyle,
    subsection_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    for msg in messages[-10:]:
        role = "You" if msg.get("role") == "user" else "Terra"
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        story.append(Paragraph(f"<b>{role}</b>", subsection_style))
        _append_markdown_narrative(
            story,
            content,
            section_style=section_style,
            subsection_style=subsection_style,
            body_style=body_style,
        )
        story.append(Spacer(1, 0.04 * inch))


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
    exploration_geometry: dict | None = None,
    analysis_area_km2: float | None = None,
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
            analysis_area_km2=analysis_area_km2,
            admin_boundary_id=boundary_id if not exploration_geometry else None,
            exploration_geometry=exploration_geometry,
            country_code=country_code,
        )

    if not ctx:
        return _gather_account_export_data(user, locale=locale, country_code=country_code)

    center = ctx.get("center") or {"lat": ctx.get("lat"), "lng": ctx.get("lng")}
    admin = _admin_from_context(ctx)
    location_name = (
        admin.get("village")
        or admin.get("ward")
        or admin.get("district")
        or admin.get("region")
        or ctx.get("geographic_region")
        or ctx.get("region")
        or "Selected area"
    )
    if exploration_geometry:
        location_name = admin.get("district") or admin.get("region") or "Exploration area"

    minerals = ctx.get("minerals", [])[:12]
    total_area_km2 = ctx.get("total_area_km2")
    if total_area_km2 is None and minerals:
        total_area_km2 = sum(float(m.get("area_km2") or 0) for m in minerals)

    regions = ctx.get("top_regions") or []
    if not regions:
        geo = ctx.get("geographic_region") or ctx.get("region")
        if geo:
            regions = [
                {
                    "region": geo,
                    "feature_count": ctx.get("feature_count", 0),
                    "area_km2": total_area_km2,
                }
            ]

    return {
        "mode": "map",
        "title": f"Terra Meta Area Brief — {location_name}",
        "subtitle": _export_subtitle(ctx, exploration_geometry=exploration_geometry),
        "country_code": country_code,
        "generated_at": timezone.now().isoformat(),
        "center": center,
        "lat": lat if lat is not None else center.get("lat"),
        "lng": lng if lng is not None else center.get("lng"),
        "zoom": zoom,
        "feature_ids": feature_ids or [],
        "location_name": location_name,
        "geographic_region": ctx.get("geographic_region") or ctx.get("region"),
        "analysis_area_km2": analysis_area_km2 or ctx.get("analysis_area_km2"),
        "insight_scope": ctx.get("insight_scope") or ctx.get("search_type"),
        "feature_count": ctx.get("feature_count", 0),
        "total_area_km2": total_area_km2,
        "minerals": minerals,
        "regions": regions[:10],
        "labels": ctx.get("labels", [])[:8],
        "top_regions": ctx.get("top_regions") or [],
        "reference_buffers": ctx.get("reference_buffers") or [],
        "direction_insights": ctx.get("direction_insights"),
        "structure_orientations": ctx.get("structure_orientations"),
        "geological_context": ctx.get("geological_context"),
        "site_assessment": (
            generate_basic_map_insight(ctx, locale=locale)
            if ctx.get("has_mapped_data")
            else ""
        ),
        "ai_context": build_search_ai_context(ctx) if ctx.get("search_name") else build_area_ai_context(ctx),
        "exploration_geometry": exploration_geometry,
        "admin": admin,
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
        if "map_snapshot" not in sections and map_kwargs.get("lat") is not None:
            sections = [*sections, "map_snapshot"]
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
        f"Total mapped areas: {data.get('total_zones') or data.get('feature_count') or 0}",
    ]
    area = data.get("total_area_km2")
    if area:
        lines.append(f"Total mineral coverage area: {area:.2f} km²")

    admin = data.get("admin") or {}
    hierarchy = [admin.get("region"), admin.get("district"), admin.get("ward"), admin.get("village")]
    hierarchy = [h for h in hierarchy if h]
    if hierarchy:
        lines.append(f"Administrative location: {' · '.join(hierarchy)}")

    if data.get("exploration_geometry"):
        geom = data["exploration_geometry"]
        lines.append(
            f"Exploration scope: user-drawn {geom.get('type', 'geometry')} on the map. "
            "Report ONLY minerals and areas inside this area."
        )

    minerals = data.get("minerals") or []
    if minerals:
        lines.append("Minerals:")
        for m in minerals[:10]:
            line = f"- {m.get('name', m.get('slug', ''))}: {m.get('count', m.get('feature_count', 0))} areas"
            if m.get("area_km2"):
                line += f", {m['area_km2']:.2f} km²"
            lines.append(line)

    regions = data.get("regions") or []
    if regions:
        lines.append("Regions:")
        for r in regions[:10]:
            name = r.get("region") or r.get("name") or "Unknown"
            count = r.get("feature_count") or r.get("count") or 0
            line = f"- {name}: {count} areas"
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
    return generate_export_narrative_text(context)


def _regions_table(regions: list[dict]) -> Table | None:
    if not regions:
        return None
    rows = [["Region", "Mapped areas", "Mineral area (km²)"]]
    for region in regions[:10]:
        name = str(region.get("region") or region.get("name") or "Unknown")
        count = int(region.get("feature_count") or region.get("count") or 0)
        area = region.get("area_km2")
        rows.append(
            [
                name,
                str(count),
                f"{float(area):,.2f}" if area else "—",
            ]
        )
    table = Table(rows, colWidths=[2.6 * inch, 1.2 * inch, 1.7 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _append_regions_section(
    story: list,
    data: dict[str, Any],
    *,
    section_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    regions = data.get("regions") or data.get("top_regions") or []
    if not regions:
        return

    location = _location_display_name(data)
    total_zones = int(data.get("feature_count") or data.get("total_zones") or 0)

    story.append(Paragraph("Where the mapped areas are", section_style))

    if len(regions) == 1:
        r = regions[0]
        name = str(r.get("region") or r.get("name") or "Unknown")
        count = int(r.get("feature_count") or r.get("count") or total_zones or 0)
        area = r.get("area_km2") or data.get("total_area_km2")
        line = (
            f"All <b>{count:,}</b> mapped area{'s' if count != 1 else ''} in this report "
            f"{'are' if count != 1 else 'is'} attributed to the <b>{_inline_markdown_markup(name)}</b> region"
        )
        if location and location.lower() != name.lower():
            line += f" (your selected area: {_inline_markdown_markup(location)})"
        if area:
            line += f", with about <b>{float(area):,.2f} km²</b> of mapped mineral coverage"
        line += "."
        story.append(Paragraph(line, body_style))
    else:
        story.append(
            Paragraph(
                "Mapped areas in your analysis area are spread across the following regions. "
                "Counts show how many prospect mineral areas fall in each region name from the layer data.",
                body_style,
            )
        )
        table = _regions_table(regions)
        if table:
            story.append(Spacer(1, 0.06 * inch))
            story.append(table)

    story.append(Spacer(1, 0.12 * inch))


def _minerals_table(minerals: list[dict]) -> Table | None:
    if not minerals:
        return None
    rows = [["Mineral", "Areas", "Area (km²)"]]
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
    export_user=None,
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
        author="Terra Meta · 5G Geology Futures",
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

    subsection_style = ParagraphStyle(
        "ExportSubsection",
        parent=section_style,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#15803d"),
        spaceBefore=10,
        spaceAfter=4,
    )

    resolved_snapshot = _resolve_map_snapshot(map_snapshot, data, user=export_user)

    story: list = []
    story.append(_wrap_text(data.get("title") or "Terra Meta Intelligence Brief", title_style))
    story.append(_wrap_text(data.get("subtitle") or "", subtitle_style))
    generated = data.get("generated_at")
    try:
        when = datetime.fromisoformat(str(generated)).strftime("%d %B %Y %H:%M UTC")
    except (TypeError, ValueError):
        when = timezone.now().strftime("%d %B %Y")
    story.append(_wrap_text(f"Generated {when} · Terra Meta Mineral Intelligence", meta_style))
    story.append(Spacer(1, 0.1 * inch))
    story.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor("#cbd5e1"),
            spaceBefore=2,
            spaceAfter=14,
        )
    )

    if data.get("mode") == "map":
        _append_location_summary(
            story,
            data,
            section_style=section_style,
            body_style=body_style,
            meta_style=meta_style,
        )

    if "map_snapshot" in sections:
        story.append(_wrap_text("Location snapshot", section_style))
        story.append(Spacer(1, 0.22 * inch))
        if resolved_snapshot:
            try:
                story.append(
                    _snapshot_image(
                        resolved_snapshot,
                        max_width=6.5 * inch,
                        max_height=5.2 * inch,
                    )
                )
                story.append(Spacer(1, 0.15 * inch))
            except Exception as exc:
                logger.warning("Map snapshot embed failed: %s", exc)
                story.append(_wrap_text("Map snapshot could not be embedded.", meta_style))
        else:
            story.append(
                _wrap_text(
                    "Map snapshot is unavailable for this location. Try exporting again from the map page.",
                    meta_style,
                )
            )

    if "overview" in sections:
        if data.get("mode") == "map":
            _append_structured_overview(
                story,
                data,
                section_style=section_style,
                subsection_style=subsection_style,
                body_style=body_style,
            )
            _append_comprehensive_map_report(
                story,
                data,
                section_style=section_style,
                subsection_style=subsection_style,
                body_style=body_style,
                meta_style=meta_style,
            )
        else:
            ai_narrative = (narrative or "").strip()
            if ai_narrative and _narrative_looks_valid(ai_narrative, data):
                _append_markdown_narrative(
                    story,
                    ai_narrative,
                    section_style=section_style,
                    subsection_style=subsection_style,
                    body_style=body_style,
                )
            else:
                _append_structured_overview(
                    story,
                    data,
                    section_style=section_style,
                    subsection_style=subsection_style,
                    body_style=body_style,
                )

    if "analytics" in sections:
        story.append(_wrap_text("Coverage analytics", section_style))
        zones = data.get("total_zones") or data.get("feature_count") or 0
        area = data.get("total_area_km2")
        minerals = data.get("minerals") or []
        analysis_km2 = data.get("analysis_area_km2")
        scope = _humanize_scope(str(data.get("insight_scope") or ""))

        lines = [f"Mapped prospect areas in scope: {int(zones):,}."]
        if area:
            lines.append(f"Total mapped mineral coverage: {float(area):,.2f} km².")
        if minerals:
            lines.append(f"Commodities represented: {len(minerals)}.")
            top = minerals[0]
            tname = top.get("name") or top.get("slug") or "Unknown"
            lines.append(
                f"Dominant commodity by area count: {tname} "
                f"({int(top.get('count') or 0):,} areas)."
            )
        if analysis_km2:
            lines.append(f"Analysis area area: ~{float(analysis_km2):,.0f} km².")
        if scope:
            lines.append(f"Spatial scope: {scope}.")
        regions = data.get("regions") or data.get("top_regions") or []
        if regions:
            lines.append(f"Administrative regions referenced: {len(regions)}.")
        for line in lines:
            story.append(_wrap_text(line, body_style))
        story.append(Spacer(1, 0.06 * inch))

    if "minerals" in sections:
        minerals = data.get("minerals") or []
        if minerals:
            story.append(_wrap_text("Mineral breakdown", section_style))
            table = _minerals_table(minerals)
            if table:
                story.append(table)
                story.append(Spacer(1, 0.12 * inch))

    if "regions" in sections:
        _append_regions_section(
            story,
            data,
            section_style=section_style,
            body_style=body_style,
        )

    if "chat" in sections and data.get("chat_messages"):
        story.append(_wrap_text("Ask Terra conversation", section_style))
        _append_chat_messages(
            story,
            data["chat_messages"],
            section_style=section_style,
            subsection_style=subsection_style,
            body_style=body_style,
        )

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
    if include_narrative and "overview" in data.get("sections", []) and data.get("mode") != "map":
        raw, _model = generate_export_narrative(data)
        narrative = sanitize_report_text(raw)

    snapshot = _decode_map_snapshot(map_snapshot_b64)
    if snapshot is None and map_snapshot_b64:
        logger.warning("Map snapshot payload could not be decoded (%d chars)", len(map_snapshot_b64))
    return build_insight_export_pdf(
        data,
        narrative=narrative,
        map_snapshot=snapshot,
        export_user=user,
    )
