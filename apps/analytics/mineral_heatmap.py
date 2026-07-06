"""Build weighted heatmap sample points from mineral map features."""

from __future__ import annotations

import math
from typing import Any

from apps.geography.admin_boundary_service import _geometry_centroid
from apps.maps.geometry_utils import geometry_area_km2, geometry_bbox, haversine_km, point_in_geometry
from apps.maps.layer_defaults import GENERAL_MINERAL_SLUG
from apps.maps.models import MapFeature, MapLayer

from .insights import _accessible_features
from .spatial_assign import feature_sample_point, layer_display_color

MAX_HEATMAP_POINTS = 28_000
LINE_SAMPLE_KM = 2.5
POLYGON_GRID_KM_MIN = 1.8
POLYGON_GRID_KM_MAX = 4.5
MAX_GRID_SAMPLES_PER_POLYGON = 64
MAX_RING_SAMPLES = 28


def _append_point(
    out: list[dict[str, float]],
    lat: float,
    lng: float,
    weight: float,
) -> None:
    if len(out) >= MAX_HEATMAP_POINTS:
        return
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return
    out.append({"lat": round(lat, 6), "lng": round(lng, 6), "weight": round(weight, 3)})


def _sample_linestring(coords: list[list[float]], *, weight: float) -> list[tuple[float, float, float]]:
    samples: list[tuple[float, float, float]] = []
    if not coords:
        return samples
    if len(coords) == 1:
        lng, lat = float(coords[0][0]), float(coords[0][1])
        samples.append((lat, lng, weight))
        return samples
    for i in range(len(coords) - 1):
        lng1, lat1 = float(coords[i][0]), float(coords[i][1])
        lng2, lat2 = float(coords[i + 1][0]), float(coords[i + 1][1])
        dist = haversine_km(lat1, lng1, lat2, lng2)
        steps = max(1, math.ceil(dist / LINE_SAMPLE_KM))
        for step in range(steps + 1):
            t = step / steps
            lat = lat1 + (lat2 - lat1) * t
            lng = lng1 + (lng2 - lng1) * t
            samples.append((lat, lng, weight))
    return samples


def _sample_ring_vertices(ring: list[list[float]], *, weight: float) -> list[tuple[float, float, float]]:
    if len(ring) < 3:
        return []
    samples: list[tuple[float, float, float]] = []
    step = max(1, len(ring) // MAX_RING_SAMPLES)
    for idx in range(0, len(ring), step):
        lng, lat = float(ring[idx][0]), float(ring[idx][1])
        samples.append((lat, lng, weight))
    return samples


def _sample_polygon_grid(geometry: dict[str, Any]) -> list[tuple[float, float, float]]:
    """Interior grid so large deposit polygons glow across their full extent."""
    bbox = geometry_bbox(geometry)
    if not bbox:
        return []
    min_lat, max_lat, min_lng, max_lng = bbox
    area = geometry_area_km2(geometry)
    spacing_km = max(
        POLYGON_GRID_KM_MIN,
        min(POLYGON_GRID_KM_MAX, math.sqrt(max(area, 0.05) / 12.0)),
    )
    spacing_deg_lat = spacing_km / 111.0
    mid_lat = (min_lat + max_lat) / 2
    spacing_deg_lng = spacing_km / (111.0 * max(0.25, math.cos(math.radians(mid_lat))))

    samples: list[tuple[float, float, float]] = []
    lat = min_lat
    while lat <= max_lat and len(samples) < MAX_GRID_SAMPLES_PER_POLYGON:
        lng = min_lng
        while lng <= max_lng and len(samples) < MAX_GRID_SAMPLES_PER_POLYGON:
            if point_in_geometry(lng, lat, geometry):
                samples.append((lat, lng, 0.78))
            lng += spacing_deg_lng
        lat += spacing_deg_lat
    return samples


def _sample_polygon_rings(geometry: dict[str, Any], *, weight: float) -> list[tuple[float, float, float]]:
    coords = geometry.get("coordinates")
    if not coords:
        return []
    gtype = geometry.get("type")
    samples: list[tuple[float, float, float]] = []
    if gtype == "Polygon" and coords[0]:
        samples.extend(_sample_ring_vertices(coords[0], weight=weight))
    elif gtype == "MultiPolygon":
        for poly in coords:
            if poly and poly[0]:
                samples.extend(_sample_ring_vertices(poly[0], weight=weight))
    return samples


def _sample_polygon(geometry: dict[str, Any]) -> list[tuple[float, float, float]]:
    coords = geometry.get("coordinates")
    if not coords:
        return []
    area = geometry_area_km2(geometry)
    centroid_weight = min(2.4, max(0.85, math.sqrt(max(area, 0.02)) / 6.0))
    lat, lng = _geometry_centroid(geometry)
    samples: list[tuple[float, float, float]] = [(lat, lng, centroid_weight)]
    samples.extend(_sample_polygon_rings(geometry, weight=0.72))
    samples.extend(_sample_polygon_grid(geometry))
    return samples


def heatmap_samples_for_feature(feature: MapFeature) -> list[tuple[float, float, float]]:
    geometry = feature.geometry
    if not geometry or "type" not in geometry:
        lat, lng = feature_sample_point(feature)
        if lat or lng:
            return [(lat, lng, 1.0)]
        return []

    gtype = geometry["type"]
    coords = geometry.get("coordinates")
    if gtype == "Point" and coords:
        return [(float(coords[1]), float(coords[0]), 1.0)]
    if gtype == "MultiPoint" and coords:
        return [(float(c[1]), float(c[0]), 1.0) for c in coords]
    if gtype == "LineString" and coords:
        return _sample_linestring(coords, weight=0.92)
    if gtype == "MultiLineString" and coords:
        out: list[tuple[float, float, float]] = []
        for line in coords:
            out.extend(_sample_linestring(line, weight=0.92))
        return out
    if gtype in ("Polygon", "MultiPolygon"):
        return _sample_polygon(geometry)
    lat, lng = feature_sample_point(feature)
    if lat or lng:
        return [(lat, lng, 1.0)]
    return []


def _layers_for_heatmap(layer_ids: list[int]) -> list[MapLayer]:
    """Resolve explicitly checked layers; all ids must belong to one mineral."""
    if not layer_ids:
        return []
    id_set = set(layer_ids)
    matched = list(
        MapLayer.objects.filter(is_active=True, id__in=id_set).select_related("mineral")
    )
    if not matched:
        return []
    mineral_slugs = {layer.mineral.slug for layer in matched}
    if len(mineral_slugs) != 1:
        return []
    return matched


def _heatmap_display_color(layers: list[MapLayer]) -> str:
    for layer_type in ("polygon", "point", "line"):
        for layer in layers:
            if layer.layer_type == layer_type:
                return layer_display_color(layer)
    return "#E87722"


def build_mineral_heatmap(
    mineral_slug: str,
    *,
    country_code: str = "TZ",
    user=None,
    layer_ids: list[int] | None = None,
    locale: str = "en",
) -> dict | None:
    from apps.maps.localization import localized_name

    mineral_slug = (mineral_slug or "").strip()
    if not layer_ids:
        return None

    mineral_layers = _layers_for_heatmap(layer_ids)
    if not mineral_layers:
        return None

    only_mineral_slug = next(iter({layer.mineral.slug for layer in mineral_layers}))
    if mineral_slug == GENERAL_MINERAL_SLUG and only_mineral_slug != GENERAL_MINERAL_SLUG:
        return None

    color = _heatmap_display_color(mineral_layers)
    if only_mineral_slug == GENERAL_MINERAL_SLUG:
        slug = mineral_layers[0].slug
    else:
        slug = only_mineral_slug
    display_name = localized_name(mineral_layers[0], locale)
    feature_counts = [
        _accessible_features(user).filter(layer=layer).count() for layer in mineral_layers
    ]
    total_features = sum(feature_counts)
    per_feature_cap = max(4, min(32, MAX_HEATMAP_POINTS // max(total_features, 1)))
    max_features_to_sample = max(1, MAX_HEATMAP_POINTS // per_feature_cap)
    pick_every = max(1, math.ceil(total_features / max_features_to_sample))

    points: list[dict[str, float]] = []
    features_used = 0
    seen_index = 0
    for layer in mineral_layers:
        if len(points) >= MAX_HEATMAP_POINTS:
            break
        for feature in _accessible_features(user).filter(layer=layer).iterator(chunk_size=256):
            if seen_index % pick_every != 0:
                seen_index += 1
                continue
            seen_index += 1
            if len(points) >= MAX_HEATMAP_POINTS:
                break
            features_used += 1
            added = 0
            for lat, lng, weight in heatmap_samples_for_feature(feature):
                if added >= per_feature_cap:
                    break
                before = len(points)
                _append_point(points, lat, lng, weight)
                if len(points) > before:
                    added += 1
                if len(points) >= MAX_HEATMAP_POINTS:
                    break

    return {
        "slug": slug,
        "name": display_name,
        "color": color,
        "feature_count": features_used,
        "point_count": len(points),
        "points": points,
    }
