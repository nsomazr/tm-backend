"""Assign map features to uploaded admin boundaries (regions, districts)."""

from __future__ import annotations

from typing import Any

from apps.geography.admin_boundary_service import _geometry_centroid
from apps.geography.models import AdminBoundary, Country
from apps.maps.geometry_utils import geometry_bbox, point_in_geometry
from apps.maps.models import MapFeature, MapLayer


def feature_sample_point(feature: MapFeature) -> tuple[float, float]:
    if feature.latitude is not None and feature.longitude is not None:
        return float(feature.latitude), float(feature.longitude)
    if feature.geometry:
        return _geometry_centroid(feature.geometry)
    return 0.0, 0.0


def feature_in_boundary_geometry(feature: MapFeature, boundary_geometry: dict) -> bool:
    if not boundary_geometry:
        return False

    lat, lng = feature_sample_point(feature)
    if lat or lng:
        if point_in_geometry(lng, lat, boundary_geometry):
            return True

    feat_bbox = geometry_bbox(feature.geometry)
    if feat_bbox:
        min_lat, max_lat, min_lng, max_lng = feat_bbox
        clat = (min_lat + max_lat) / 2
        clng = (min_lng + max_lng) / 2
        if point_in_geometry(clng, clat, boundary_geometry):
            return True

    return False


def boundary_center_and_bounds(boundary: AdminBoundary) -> tuple[dict | None, dict | None]:
    bbox = geometry_bbox(boundary.geometry)
    if bbox:
        min_lat, max_lat, min_lng, max_lng = bbox
        return (
            {"lat": (min_lat + max_lat) / 2, "lng": (min_lng + max_lng) / 2},
            {"west": min_lng, "south": min_lat, "east": max_lng, "north": max_lat},
        )
    if boundary.center_lat is not None and boundary.center_lng is not None:
        return {"lat": boundary.center_lat, "lng": boundary.center_lng}, None
    return None, None


def features_in_boundary(boundary: AdminBoundary, features: list[MapFeature]) -> list[MapFeature]:
    boundary_bbox = geometry_bbox(boundary.geometry)
    matched: list[MapFeature] = []
    for feature in features:
        if boundary_bbox:
            feat_bbox = geometry_bbox(feature.geometry)
            lat, lng = feature_sample_point(feature)
            min_lat, max_lat, min_lng, max_lng = boundary_bbox
            if feat_bbox:
                f_min_lat, f_max_lat, f_min_lng, f_max_lng = feat_bbox
                if f_max_lat < min_lat or f_min_lat > max_lat or f_max_lng < min_lng or f_min_lng > max_lng:
                    if not (min_lat <= lat <= max_lat and min_lng <= lng <= max_lng):
                        continue
            elif not (min_lat <= lat <= max_lat and min_lng <= lng <= max_lng):
                continue
        if feature_in_boundary_geometry(feature, boundary.geometry):
            matched.append(feature)
    return matched


class AdminBoundaryIndex:
    """Uploaded admin boundaries for point-in-polygon region resolution."""

    def __init__(
        self,
        country_code: str = "TZ",
        *,
        levels: tuple[int, ...] = (AdminBoundary.Level.REGION,),
        uploaded_only: bool = True,
    ):
        self.entries: list[tuple[str, dict, tuple[float, float, float, float] | None]] = []
        country = Country.objects.filter(code=country_code.upper()).first()
        if not country:
            return
        qs = AdminBoundary.objects.filter(country=country, level__in=levels)
        if uploaded_only:
            qs = qs.filter(source=AdminBoundary.Source.ADMIN_UPLOAD)
        for boundary in qs.only("name", "geometry"):
            self.entries.append(
                (boundary.name, boundary.geometry, geometry_bbox(boundary.geometry))
            )

    def resolve_name(self, lat: float, lng: float) -> str | None:
        for name, geometry, bbox in self.entries:
            if bbox:
                min_lat, max_lat, min_lng, max_lng = bbox
                if not (min_lat <= lat <= max_lat and min_lng <= lng <= max_lng):
                    continue
            if point_in_geometry(lng, lat, geometry):
                return name
        return None


def layer_display_color(layer) -> str:
    style = layer.style or {}
    if layer.layer_type == "line":
        return style.get("stroke") or style.get("fill") or "#64748b"
    return style.get("fill") or layer.mineral.color or "#0d9488"


def commodities_from_features(
    features: list[MapFeature],
    locale: str = "en",
    *,
    include_polygon_area: bool = False,
) -> list[dict[str, Any]]:
    from apps.maps.geometry_utils import geometry_area_km2
    from apps.maps.localization import localized_name

    counts: dict[int, dict[str, Any]] = {}
    for feature in features:
        layer = feature.layer
        if layer.id not in counts:
            entry: dict[str, Any] = {
                "slug": layer.slug,
                "name": localized_name(layer, locale),
                "name_sw": layer.name_sw or "",
                "color": layer_display_color(layer),
                "count": 0,
            }
            if include_polygon_area:
                entry["area_km2"] = 0.0
            counts[layer.id] = entry
        counts[layer.id]["count"] += 1
        if include_polygon_area and layer.layer_type == MapLayer.LayerType.POLYGON:
            counts[layer.id]["area_km2"] += geometry_area_km2(feature.geometry)

    rows: list[dict[str, Any]] = []
    for row in counts.values():
        if include_polygon_area:
            area = float(row.pop("area_km2", 0.0) or 0.0)
            if area > 0:
                row["area_km2"] = round(area, 4)
        rows.append(row)
    return sorted(rows, key=lambda item: item["count"], reverse=True)
