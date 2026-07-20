"""Standard Terra Meta map-click report structure."""

from __future__ import annotations

import re
from typing import Any

MAP_REPORT_SECTIONS: tuple[str, ...] = (
    "Executive Summary",
    "Geological Information",
    "Results / Findings",
    "Logistics",
    "Snapshot / Figure",
    "Recommendation",
    "Conclusion",
)

MAP_INSIGHT_STRUCTURE_INSTRUCTION = (
    "Write a structured exploration brief using ONLY the mapped data provided. "
    "Use markdown headings exactly as shown below. Use # once for the title line only; "
    "use ## for every section heading. Write 1-3 short paragraphs per section. "
    "Use **bold** sparingly for mineral and place names. "
    "Do not use bullet lists except in Results / Findings (optional hyphen bullets). "
    "Terminology: call mapped line-type geological features structures, never lines or lineaments in user-facing text. "
    "Required structure:\n\n"
    "# {concise area title with main commodity if known}\n\n"
    "## Executive Summary\n"
    "Location, analysis scope, and the main exploration takeaway.\n\n"
    "## Geological Information\n"
    "Mapped commodities, occurrences vs polygon areas, structure, terrain, and geological context.\n\n"
    "## Results / Findings\n"
    "Specific counts, areas, compass clustering, and mapped evidence from the data.\n\n"
    "## Logistics\n"
    "Administrative region, hierarchy, coordinates, analysis area size, accessibility, and how to work the ground.\n\n"
    "## Snapshot / Figure\n"
    "Describe what the map view shows for this location (layers, footprint, and visual context).\n\n"
    "## Recommendation\n"
    "Prioritised next steps for exploration teams and due diligence.\n\n"
    "## Conclusion\n"
    "Closing summary with data limitations and whether follow-up is warranted."
)

_SECTION_ALIASES: dict[str, str] = {
    "geology": "Geological Information",
    "geological information": "Geological Information",
    "geological interpretation": "Geological Information",
    "result / findings": "Results / Findings",
    "results / findings": "Results / Findings",
    "results and findings": "Results / Findings",
    "key findings": "Results / Findings",
    "findings": "Results / Findings",
    "logistics and access": "Logistics",
    "infrastructure, access, and jurisdiction": "Logistics",
    "location summary": "Logistics",
    "location analysis": "Logistics",
    "snapshot": "Snapshot / Figure",
    "snapshot / figure": "Snapshot / Figure",
    "figure": "Snapshot / Figure",
    "location snapshot": "Snapshot / Figure",
    "recommendations": "Recommendation",
    "recommendation and next steps": "Recommendation",
    "exploration recommendations": "Recommendation",
    "recommendations and next steps": "Recommendation",
}


def normalize_map_insight_terminology(text: str) -> str:
    """Prefer structures over lines in map insight and report prose."""
    if not text:
        return text
    replacements = (
        (r"\bStructure lines\b", "Structures"),
        (r"\bstructure lines\b", "structures"),
        (r"\bStructure line\b", "Structure"),
        (r"\bstructure line\b", "structure"),
        (r"\bline geometry\b", "structure geometry"),
        (r"\bLine geometry\b", "Structure geometry"),
        (r"\bmapped lines\b", "mapped structures"),
        (r"\bMapped lines\b", "Mapped structures"),
        (r"\bline features\b", "structures"),
        (r"\bLine features\b", "Structures"),
        (r"\bline feature\b", "structure"),
        (r"\bLine feature\b", "Structure"),
    )
    result = text
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    return result


def normalize_map_report_section_heading(text: str) -> str | None:
    cleaned = re.sub(r"^#{1,6}\s*", "", (text or "").strip())
    if not cleaned:
        return None
    lower = cleaned.lower().rstrip(":")
    for section in MAP_REPORT_SECTIONS:
        if section.lower() == lower:
            return section
    return _SECTION_ALIASES.get(lower)


def parse_map_report_markdown(text: str) -> dict[str, str]:
    """Parse markdown map report into section name -> body."""
    sections: dict[str, str] = {}
    if not (text or "").strip():
        return sections

    title_match = re.match(r"^#\s+(.+)$", text.strip(), flags=re.MULTILINE)
    if title_match:
        sections["Title"] = title_match.group(1).strip()

    current: str | None = None
    buffer: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = None
        if line.startswith("#"):
            heading = normalize_map_report_section_heading(line)
        elif line and not line.endswith(".") and len(line) < 80:
            heading = normalize_map_report_section_heading(line)
        if heading:
            if current and buffer:
                sections[current] = "\n".join(buffer).strip()
            current = heading
            buffer = []
            continue
        if current:
            buffer.append(raw_line.rstrip())
    if current and buffer:
        sections[current] = "\n".join(buffer).strip()
    return sections


def format_map_report_markdown(sections: dict[str, str], *, title: str) -> str:
    parts = [f"# {title.strip()}", ""]
    for name in MAP_REPORT_SECTIONS:
        body = (sections.get(name) or "").strip()
        if not body:
            continue
        parts.extend([f"## {name}", body, ""])
    return "\n".join(parts).strip()


def _snapshot_note(ctx: dict[str, Any], *, locale: str = "en") -> str:
    lat, lng = ctx.get("lat"), ctx.get("lng")
    minerals = ctx.get("minerals") or []
    feature_count = int(ctx.get("feature_count") or 0)
    if locale == "sw":
        base = "Muonekano wa ramani unaoonyesha eneo la uchambuzi"
        if lat is not None and lng is not None:
            base += f" karibu na {float(lat):.4f}, {float(lng):.4f}"
        if feature_count:
            base += f" na vipengele {feature_count} vilivyopangwa"
        if minerals:
            names = ", ".join((m.get("name") or m.get("slug") or "Madini") for m in minerals[:3])
            base += f" kwa madini kama {names}"
        return base + ". Tumia picha ya ramani iliyopo pamoja na ripoti hii kwa muktadha wa nafasi."
    base = "The map view captures the analysis area"
    if lat is not None and lng is not None:
        base += f" centred at {float(lat):.5f}, {float(lng):.5f}"
    if feature_count:
        base += f" with {feature_count} mapped feature{'s' if feature_count != 1 else ''}"
    if minerals:
        names = ", ".join((m.get("name") or m.get("slug") or "Unknown") for m in minerals[:3])
        base += f" for commodities including {names}"
    return (
        base
        + ". Use the accompanying map snapshot with this report for spatial context, target footprints, and nearby mapped layers."
    )


def build_map_report_sections(ctx: dict[str, Any], *, locale: str = "en") -> dict[str, str]:
    from .insights import (
        _admin_hierarchy_lines,
        _location_label,
        _mineral_exploration_notes,
        _scope_narrative,
        generate_unmapped_insight,
    )

    if not ctx.get("has_mapped_data"):
        unmapped = generate_unmapped_insight(ctx["lat"], ctx["lng"], locale)
        return {
            "Title": _location_label(ctx, locale=locale),
            "Executive Summary": unmapped,
            "Geological Information": (
                "No mapped mineral features were found in this analysis scope. "
                "Consult regional geological maps and literature for broader context."
                if locale != "sw"
                else "Hakuna vipengele vya madini vilivyopangwa katika upeo huu. Tumia ramani za kikanda kwa muktadha mpana."
            ),
            "Results / Findings": (
                "- No mapped occurrences or polygon areas in the current search radius."
                if locale != "sw"
                else "- Hakuna matukio au poligoni zilizopangwa katika upeo wa sasa."
            ),
            "Logistics": _admin_hierarchy_lines(ctx, locale=locale) or _location_label(ctx, locale=locale),
            "Snapshot / Figure": _snapshot_note(ctx, locale=locale),
            "Recommendation": (
                "Expand the search radius, review cadastre records, and consult licensed geological survey data before field work."
                if locale != "sw"
                else "Panua eneo la utafiti, kagua rekodi za leseni, na tumia data ya utafiti wa kijiolojia kabla ya shambani."
            ),
            "Conclusion": (
                "This location requires wider desktop review before exploration commitments."
                if locale != "sw"
                else "Eneo hili linahitaji ukaguzi wa mezani kabla ya uamuzi wa uchunguzi."
            ),
        }

    minerals = ctx.get("minerals", [])
    geo = ctx.get("geographic_region") or ctx.get("region") or ("Haijulikani" if locale == "sw" else "Unassigned")
    location = _location_label(ctx, locale=locale)
    admin_lines = _admin_hierarchy_lines(ctx, locale=locale)
    zone_km2 = ctx.get("analysis_area_km2")
    scope = ctx.get("insight_scope") or "analysis_zone"
    feature_count = int(ctx.get("feature_count") or 0)
    occurrence_count = int(ctx.get("occurrence_count") or 0)
    polygon_count = int(ctx.get("polygon_count") or 0)
    labels = ctx.get("labels") or []
    lat, lng = ctx.get("lat"), ctx.get("lng")
    primary = minerals[0].get("name") or minerals[0].get("slug") if minerals else None
    title = f"{location} — {primary}" if primary else f"{location} — Mineral Intelligence"

    if locale == "sw":
        executive = (
            f"Muhtasari wa uchunguzi kwa **{location}** katika mkoa wa **{geo}**. "
            f"{_scope_narrative(scope, locale)}"
        )
        if zone_km2:
            executive += f" Eneo la uchambuzi ni takriban **{zone_km2:,.0f} km²**."
        if feature_count:
            executive += (
                f" Data inaonyesha **{feature_count}** kipengele kilichopangwa "
                f"({occurrence_count} matukio ya nukta, {polygon_count} maeneo ya poligoni)."
            )
    else:
        executive = (
            f"Exploration brief for **{location}** in the **{geo}** region. "
            f"{_scope_narrative(scope, locale)}"
        )
        if zone_km2:
            executive += f" The analysis covers approximately **{zone_km2:,.0f} km²**."
        if feature_count:
            executive += (
                f" Mapped data includes **{feature_count}** features "
                f"({occurrence_count} point occurrence{'s' if occurrence_count != 1 else ''}, "
                f"{polygon_count} polygon mineral area{'s' if polygon_count != 1 else ''})."
            )

    geology_parts: list[str] = []
    for mineral in minerals[:4]:
        mname = mineral.get("name") or mineral.get("slug") or ("Madini" if locale == "sw" else "Unknown")
        m_occ = int(mineral.get("occurrence_count") or 0)
        m_poly = int(mineral.get("polygon_count") or 0)
        detail_bits = []
        if m_occ:
            detail_bits.append(f"{m_occ} occurrence{'s' if m_occ != 1 else ''}" if locale != "sw" else f"{m_occ} tukio")
        if m_poly:
            detail_bits.append(f"{m_poly} polygon area{'s' if m_poly != 1 else ''}" if locale != "sw" else f"{m_poly} poligoni")
        lead = f"**{mname}** ({', '.join(detail_bits) or str(mineral.get('count') or 0)})"
        if mineral.get("area_km2"):
            lead += f", {float(mineral['area_km2']):,.2f} km²"
        lead += f": {_mineral_exploration_notes(mineral.get('slug', ''), mname, locale)}"
        geology_parts.append(lead)
    for line in (ctx.get("direction_insights") or {}).get("summary_lines") or []:
        geology_parts.append(line)
    for line in (ctx.get("structure_orientations") or {}).get("summary_lines") or []:
        geology_parts.append(line)
    for line in (ctx.get("terrain_context") or {}).get("summary_lines") or []:
        geology_parts.append(line)
    if labels:
        geology_parts.append(
            f"Mapped labels: {', '.join(labels[:5])}."
            if locale != "sw"
            else f"Lebo zilizopangwa: {', '.join(labels[:5])}."
        )

    findings: list[str] = []
    if zone_km2:
        findings.append(
            f"Analysis area ~{float(zone_km2):,.0f} km² centred on {location}."
            if locale != "sw"
            else f"Eneo la uchambuzi ~{float(zone_km2):,.0f} km² karibu na {location}."
        )
    if feature_count:
        findings.append(
            f"{feature_count} mapped features in scope ({occurrence_count} occurrences, {polygon_count} polygons)."
            if locale != "sw"
            else f"Vipengele {feature_count} katika upeo ({occurrence_count} matukio, {polygon_count} poligoni)."
        )
    line_count = int(ctx.get("line_count") or 0)
    if line_count:
        findings.append(
            f"{line_count} mapped structure{'s' if line_count != 1 else ''} in scope."
            if locale != "sw"
            else f"Miundo {line_count} yaliyopangwa katika upeo."
        )
    for mineral in minerals[:5]:
        name = mineral.get("name") or mineral.get("slug") or "Unknown"
        count = int(mineral.get("count") or 0)
        line = f"{name}: {count} mapped area{'s' if count != 1 else ''}"
        if mineral.get("area_km2"):
            line += f", {float(mineral['area_km2']):,.2f} km²"
        findings.append(line + ".")

    logistics_parts = []
    if admin_lines:
        logistics_parts.append(admin_lines)
    if lat is not None and lng is not None:
        logistics_parts.append(
            f"Reference coordinates: {float(lat):.5f}, {float(lng):.5f} (WGS84)."
            if locale != "sw"
            else f"Kuratibu: {float(lat):.5f}, {float(lng):.5f} (WGS84)."
        )
    if zone_km2:
        logistics_parts.append(
            f"Circular analysis area of ~{float(zone_km2):,.0f} km²; plan access routes, cadastre checks, and camp logistics accordingly."
            if locale != "sw"
            else f"Eneo la uchambuzi ~{float(zone_km2):,.0f} km²; panga njia za ufikiaji na ukaguzi wa leseni."
        )
    logistics_parts.append(
        f"Regional frame: **{geo}**, Tanzania. Confirm district roads, tenure, and environmental constraints before mobilisation."
        if locale != "sw"
        else f"Mwelekeo wa kikanda: **{geo}**, Tanzania. Thibitisha barabara, leseni, na vizuizi vya mazingira kabla ya kazi."
    )

    if feature_count <= 2:
        recommendation = (
            "Prioritise a rank-1 desktop review, licence confirmation, reconnaissance mapping, "
            "and infill geochemistry on the mapped footprint before drill commitments."
            if locale != "sw"
            else "Anza na ukaguzi wa mezani, uthibitishaji wa leseni, ramani ya shamba, na jeochemistry kabla ya kuchimba."
        )
    else:
        recommendation = (
            "Rank targets by commodity, polygon area, and access; sequence reconnaissance mapping, "
            "geochemistry, commodity-appropriate geophysics, then trenching or scout drilling on the strongest targets."
            if locale != "sw"
            else "Panga malengo kwa madini, eneo, na ufikiaji; fuata ramani, jeochemistry, geophysiki, kisha trenching au kuchimba."
        )

    conclusion = (
        "This brief is generated from Terra Meta mapped layers only. It supports exploration planning "
        "and due diligence but does not include drill intercepts, resource models, or economic studies."
        if locale != "sw"
        else "Ripoti hii inategemea tabaka za Terra Meta pekee na haijumuishi matokeo ya kuchimba wala makadirio ya akiba."
    )

    return {
        "Title": title,
        "Executive Summary": executive,
        "Geological Information": " ".join(geology_parts),
        "Results / Findings": "\n".join(f"- {item}" for item in findings),
        "Logistics": " ".join(logistics_parts),
        "Snapshot / Figure": _snapshot_note(ctx, locale=locale),
        "Recommendation": recommendation,
        "Conclusion": conclusion,
    }


def build_map_report_markdown(ctx: dict[str, Any], *, locale: str = "en") -> str:
    sections = build_map_report_sections(ctx, locale=locale)
    title = sections.pop("Title", _location_fallback(ctx))
    return normalize_map_insight_terminology(format_map_report_markdown(sections, title=title))


def _location_fallback(ctx: dict[str, Any]) -> str:
    lat, lng = ctx.get("lat"), ctx.get("lng")
    if lat is not None and lng is not None:
        return f"Map location {float(lat):.4f}, {float(lng):.4f}"
    return "Selected map area"
