"""Build weighted heatmap sample points from mineral map features."""

from __future__ import annotations

import math
from typing import Any

from apps.geography.admin_boundary_service import _geometry_centroid
from apps.geography.models import Country
from apps.maps.geometry_utils import geometry_area_km2, haversine_km
from apps.maps.models import MapFeature, MapLayer
from apps.minerals.models import Mineral

from .insights import _accessible_features
from .mineral_coverage import PERIODIC_LAYER_SLUGS, _find_layer_for_catalog_slug
from .spatial_assign import feature_sample_point, layer_display_color

MAX_HEATMAP_FEATURES = 5000
MAX_HEATMAP_POINTS = 14000
LINE_SAMPLE_KM = 2.5


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
    step = max(1, len(ring) // 12)
    for idx in range(0, len(ring), step):
        lng, lat = float(ring[idx][0]), float(ring[idx][1])
        samples.append((lat, lng, weight))
    return samples


def _sample_polygon(geometry: dict[str, Any]) -> list[tuple[float, float, float]]:
    coords = geometry.get("coordinates")
    if not coords:
        return []
    area = geometry_area_km2(geometry)
    centroid_weight = min(2.4, max(0.85, math.sqrt(max(area, 0.02)) / 6.0))
    lat, lng = _geometry_centroid(geometry)
    samples: list[tuple[float, float, float]] = [(lat, lng, centroid_weight)]
    gtype = geometry.get("type")
    if gtype == "Polygon":
        samples.extend(_sample_ring_vertices(coords[0], weight=0.72))
    elif gtype == "MultiPolygon":
        for poly in coords[:6]:
            if poly and poly[0]:
                samples.extend(_sample_ring_vertices(poly[0], weight=0.72))
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


def _layers_for_heatmap(
    mineral_slug: str,
    layers: list[MapLayer],
    layer_ids: list[int] | None = None,
) -> list[MapLayer]:
    """All active map layers for a mineral, optionally filtered to visible layer ids."""
    slug_candidates = set(PERIODIC_LAYER_SLUGS.get(mineral_slug, [mineral_slug]))
    matched: list[MapLayer] = []
    seen: set[int] = set()
    for layer in layers:
        if layer.id in seen:
            continue
        if layer.mineral.slug == mineral_slug or layer.slug in slug_candidates:
            seen.add(layer.id)
            matched.append(layer)
    if layer_ids:
        id_set = set(layer_ids)
        matched = [layer for layer in matched if layer.id in id_set]
    if matched:
        return matched
    single = _find_layer_for_catalog_slug(mineral_slug, layers)
    if single and (not layer_ids or single.id in layer_ids):
        return [single]
    return []


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
    max_features: int = MAX_HEATMAP_FEATURES,
    locale: str = "en",
) -> dict | None:
    from apps.maps.localization import localized_name

    country = Country.objects.filter(code=country_code.upper()).first()
    if not country:
        return None

    layers = list(
        MapLayer.objects.filter(is_active=True, mineral__country=country).select_related("mineral")
    )
    mineral_layers = _layers_for_heatmap(mineral_slug, layers, layer_ids)
    if not mineral_layers:
        try:
            mineral = Mineral.objects.get(slug=mineral_slug, is_active=True, country=country)
        except Mineral.DoesNotExist:
            return None
        features = list(_accessible_features(user, mineral_slug=mineral_slug)[:max_features])
        color = mineral.color
        slug = mineral.slug
        display_name = localized_name(mineral, locale)
    else:
        color = _heatmap_display_color(mineral_layers)
        slug = mineral_slug
        display_name = localized_name(mineral_layers[0], locale)
        features = []
        remaining = max_features
        for layer in mineral_layers:
            if remaining <= 0:
                break
            batch = list(_accessible_features(user).filter(layer=layer)[:remaining])
            features.extend(batch)
            remaining -= len(batch)

    points: list[dict[str, float]] = []
    for feature in features:
        for lat, lng, weight in heatmap_samples_for_feature(feature):
            _append_point(points, lat, lng, weight)
            if len(points) >= MAX_HEATMAP_POINTS:
                break
        if len(points) >= MAX_HEATMAP_POINTS:
            break

    return {
        "slug": slug,
        "name": display_name,
        "color": color,
        "feature_count": len(features),
        "point_count": len(points),
        "points": points,
    }
