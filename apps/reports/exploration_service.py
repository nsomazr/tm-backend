"""User-generated geological exploration reports."""

from __future__ import annotations

from apps.analytics.insight_export import gather_insight_export_data, _build_data_context_block

from .ai_service import generate_exploration_report
from .models import UserExplorationReport


def _context_block_from_report(record: UserExplorationReport) -> str:
    ctx = record.context or {}
    user = record.user
    data = gather_insight_export_data(
        user,
        mode="map" if ctx.get("lat") is not None and ctx.get("lng") is not None else "account",
        lat=ctx.get("lat"),
        lng=ctx.get("lng"),
        zoom=ctx.get("zoom"),
        mineral_slug=ctx.get("mineral_slug", ""),
        region_id=ctx.get("region_id"),
        layer_id=ctx.get("layer_id"),
        boundary_id=ctx.get("boundary_id"),
        feature_ids=ctx.get("feature_ids"),
        exploration_geometry=ctx.get("exploration_geometry"),
        locale=ctx.get("locale", "en"),
    )
    return _build_data_context_block(data)


def generate_exploration_draft(record: UserExplorationReport) -> UserExplorationReport:
    record.status = UserExplorationReport.Status.GENERATING
    record.error_message = ""
    record.save(update_fields=["status", "error_message", "updated_at"])

    try:
        context_block = _context_block_from_report(record)
        prompt = record.prompt
        if record.revision_notes.strip():
            prompt = f"{prompt}\n\nRevision notes:\n{record.revision_notes.strip()}"

        sections, model_used = generate_exploration_report(context_block, prompt)
        record.title = sections.get("title") or record.title or "Exploration report"
        record.sections = sections
        record.narrative = _sections_to_narrative(sections)
        record.status = UserExplorationReport.Status.READY
        record.context = {**(record.context or {}), "model_used": model_used}
        record.save(
            update_fields=[
                "title",
                "sections",
                "narrative",
                "status",
                "context",
                "updated_at",
            ]
        )
    except Exception as exc:
        record.status = UserExplorationReport.Status.FAILED
        record.error_message = str(exc)
        record.save(update_fields=["status", "error_message", "updated_at"])
    return record


def _sections_to_narrative(sections: dict) -> str:
    parts = []
    for key, heading in (
        ("executive_summary", "Executive Summary"),
        ("geological_interpretation", "Geological Interpretation"),
        ("layer_analysis", "Layer Analysis"),
        ("location_analysis", "Location Analysis"),
        ("analytics_narrative", "Analytics"),
        ("data_references", "Data References"),
    ):
        value = sections.get(key)
        if value:
            parts.append(f"{heading}\n{value}")
    recommendations = sections.get("recommendations") or []
    if recommendations:
        parts.append("Recommendations\n" + "\n".join(f"- {item}" for item in recommendations))
    return "\n\n".join(parts)
