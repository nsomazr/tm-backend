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


def features_in_exploration_scope(
    features: list[MapFeature],
    exploration_geometry: dict[str, Any],
    *,
    point_buffer_km: float = 1.5,
    line_buffer_km: float = 2.0,
) -> list[MapFeature]:
    """Keep only features that fall inside a user-drawn exploration geometry."""
    from apps.maps.geometry_utils import distance_geometry_to_point_km, haversine_km

    if not exploration_geometry or "type" not in exploration_geometry:
        return []

    gtype = exploration_geometry.get("type")
    coords = exploration_geometry.get("coordinates")
    if not coords:
        return []

    matched: list[MapFeature] = []
    for feature in features:
        if gtype == "Polygon":
            if feature_in_boundary_geometry(feature, exploration_geometry):
                matched.append(feature)
            continue

        flat, flng = feature_sample_point(feature)

        if gtype == "Point":
            elng, elat = float(coords[0]), float(coords[1])
            if (
                haversine_km(flat, flng, elat, elng) <= point_buffer_km
                or distance_geometry_to_point_km(elat, elng, feature.geometry) <= point_buffer_km
            ):
                matched.append(feature)
            continue

        if gtype == "LineString":
            min_dist = float("inf")
            for vertex in coords:
                d = distance_geometry_to_point_km(float(vertex[1]), float(vertex[0]), feature.geometry)
                min_dist = min(min_dist, d)
            if min_dist <= line_buffer_km:
                matched.append(feature)

    return matched


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


def is_point_feature(feature: MapFeature) -> bool:
    """True when the feature is a mapped point occurrence (not a polygon area)."""
    layer = getattr(feature, "layer", None)
    if layer is not None and layer.layer_type == MapLayer.LayerType.POINT:
        return True
    geometry = feature.geometry if isinstance(feature.geometry, dict) else {}
    return geometry.get("type") in ("Point", "MultiPoint")


def is_polygon_feature(feature: MapFeature) -> bool:
    layer = getattr(feature, "layer", None)
    if layer is not None and layer.layer_type == MapLayer.LayerType.POLYGON:
        return True
    geometry = feature.geometry if isinstance(feature.geometry, dict) else {}
    return geometry.get("type") in ("Polygon", "MultiPolygon")


def is_line_feature(feature: MapFeature) -> bool:
    """True when the feature is a mapped structure line (not a point or polygon area)."""
    layer = getattr(feature, "layer", None)
    if layer is not None and layer.layer_type == MapLayer.LayerType.LINE:
        return True
    geometry = feature.geometry if isinstance(feature.geometry, dict) else {}
    return geometry.get("type") in ("LineString", "MultiLineString")


def commodities_from_features(
    features: list[MapFeature],
    locale: str = "en",
    *,
    include_polygon_area: bool = False,
    area_clip_lat: float | None = None,
    area_clip_lng: float | None = None,
    area_clip_km2: float | None = None,
) -> list[dict[str, Any]]:
    from apps.maps.geometry_utils import geometry_area_in_circle_km2, geometry_area_km2
    from apps.maps.localization import localized_name
    from apps.analytics.map_view_area import analysis_zone_radius_km

    clip_radius_km = None
    if (
        include_polygon_area
        and area_clip_lat is not None
        and area_clip_lng is not None
        and area_clip_km2
        and float(area_clip_km2) > 0
    ):
        clip_radius_km = analysis_zone_radius_km(float(area_clip_km2))

    counts: dict[int, dict[str, Any]] = {}
    for feature in features:
        layer = feature.layer
        if layer.id not in counts:
            entry: dict[str, Any] = {
                "slug": layer.slug,
                "name": localized_name(layer, locale),
                "name_sw": layer.name_sw or "",
                "color": layer_display_color(layer),
                # Total mapped features (points + polygons + lines) for list UIs.
                "count": 0,
                # Occurrences = point features only (insights / reporting).
                "occurrence_count": 0,
                "polygon_count": 0,
                "line_count": 0,
            }
            if include_polygon_area:
                entry["area_km2"] = 0.0
            counts[layer.id] = entry
        counts[layer.id]["count"] += 1
        if is_point_feature(feature):
            counts[layer.id]["occurrence_count"] += 1
        elif is_polygon_feature(feature):
            counts[layer.id]["polygon_count"] += 1
            if include_polygon_area:
                if clip_radius_km is not None:
                    counts[layer.id]["area_km2"] += geometry_area_in_circle_km2(
                        feature.geometry,
                        float(area_clip_lat),
                        float(area_clip_lng),
                        clip_radius_km,
                    )
                else:
                    counts[layer.id]["area_km2"] += geometry_area_km2(feature.geometry)
        elif is_line_feature(feature):
            counts[layer.id]["line_count"] += 1

    rows: list[dict[str, Any]] = []
    for row in counts.values():
        if include_polygon_area:
            area = float(row.pop("area_km2", 0.0) or 0.0)
            if area > 0:
                row["area_km2"] = round(area, 4)
        rows.append(row)
    return sorted(rows, key=lambda item: item["count"], reverse=True)
