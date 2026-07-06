"""Match catalog reports to map context for contextual insights."""

from __future__ import annotations

from apps.geography.admin_boundary_service import lookup_boundaries_at_point
from apps.geography.models import AdminBoundary, Country
from apps.maps.models import MapLayer

from .models import Report
from .serializers import ReportSerializer


def _point_in_bbox(lat: float, lng: float, bbox: dict) -> bool:
    if not bbox:
        return False
    west = bbox.get("west")
    south = bbox.get("south")
    east = bbox.get("east")
    north = bbox.get("north")
    if None in (west, south, east, north):
        return False
    return south <= lat <= north and west <= lng <= east


def _score_report(
    report: Report,
    *,
    lat: float | None,
    lng: float | None,
    mineral_slug: str,
    layer_ids: set[int],
    boundary_ids: set[int],
) -> int:
    score = 0
    if mineral_slug and report.mineral.slug == mineral_slug:
        score += 2
    if layer_ids:
        linked = set(report.layers.values_list("id", flat=True))
        if linked & layer_ids:
            score += 4
    if boundary_ids:
        linked_b = set(report.boundaries.values_list("id", flat=True))
        if linked_b & boundary_ids:
            score += 6
    if lat is not None and lng is not None:
        if _point_in_bbox(lat, lng, report.bounding_box or {}):
            score += 5
        if report.center_lat is not None and report.center_lng is not None:
            dlat = abs(report.center_lat - lat)
            dlng = abs(report.center_lng - lng)
            if dlat < 0.5 and dlng < 0.5:
                score += 3
    return score


def find_contextual_reports(
    *,
    lat: float | None = None,
    lng: float | None = None,
    mineral_slug: str = "",
    layer_ids: list[int] | None = None,
    boundary_id: int | None = None,
    country_code: str = "TZ",
    limit: int = 6,
    request=None,
) -> list[dict]:
    layer_id_set = set(layer_ids or [])
    boundary_ids: set[int] = set()
    if boundary_id:
        boundary_ids.add(boundary_id)
    if lat is not None and lng is not None:
        country = Country.objects.filter(code=country_code.upper()).first()
        if country:
            hit = lookup_boundaries_at_point(country, lat, lng)
            for key in ("region", "district", "ward", "village"):
                row = hit.get(key)
                if row and row.get("id"):
                    boundary_ids.add(int(row["id"]))

    qs = (
        Report.objects.filter(is_active=True)
        .select_related("mineral", "region")
        .prefetch_related("ai_summary", "layers", "boundaries", "purchases")
    )
    if mineral_slug:
        qs = qs.filter(mineral__slug=mineral_slug)

    scored: list[tuple[int, Report]] = []
    for report in qs:
        score = _score_report(
            report,
            lat=lat,
            lng=lng,
            mineral_slug=mineral_slug,
            layer_ids=layer_id_set,
            boundary_ids=boundary_ids,
        )
        if score > 0:
            scored.append((score, report))

    scored.sort(key=lambda row: (-row[0], row[1].title))
    top = [report for _, report in scored[:limit]]

    serializer = ReportSerializer(
        top,
        many=True,
        context={"request": request, "preview_mode": "list"},
    )
    results = serializer.data
    for item, (score, report) in zip(results, scored[:limit], strict=False):
        item["relevance_score"] = score
        item["linked_layer_slugs"] = list(report.layers.values_list("slug", flat=True))
        item["linked_boundary_names"] = list(report.boundaries.values_list("name", flat=True)[:5])
    return results
