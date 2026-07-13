"""Marketplace listing geometry: Point / MultiPoint / Polygon / MultiPolygon."""

from __future__ import annotations

from typing import Any

from apps.reports.geometry import (
    _expand_bbox,
    _ring_points,
    clamp_report_buffer_km,
    derive_center_and_bbox as _derive_simple,
)

# Cap extracted features from a single upload (licence blocks / sites).
MARKETPLACE_UPLOAD_MAX_FEATURES = 2_000


def _normalize_point(coords) -> list[float]:
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        raise ValueError("Point geometry requires [lng, lat] coordinates.")
    lng, lat = float(coords[0]), float(coords[1])
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        raise ValueError("Point coordinates are out of range.")
    return [lng, lat]


def _normalize_polygon_ring(coords) -> list[list[float]]:
    points = _ring_points(coords)
    if len(points) < 3:
        raise ValueError("Polygon geometry requires at least 3 vertices.")
    ring = [[lng, lat] for lng, lat in points]
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    if len(ring) < 4:
        raise ValueError("Polygon geometry requires a closed ring.")
    return ring


def normalize_listing_geometry(value) -> dict:
    """Return cleaned GeoJSON Point/MultiPoint/Polygon/MultiPolygon, or {}."""
    if value in (None, "", {}, []):
        return {}
    if not isinstance(value, dict):
        raise ValueError("geometry must be a GeoJSON object.")

    gtype = value.get("type")
    coords = value.get("coordinates")

    if gtype == "Point":
        return {"type": "Point", "coordinates": _normalize_point(coords)}

    if gtype == "MultiPoint":
        if not isinstance(coords, (list, tuple)) or not coords:
            raise ValueError("MultiPoint requires at least one position.")
        points = [_normalize_point(c) for c in coords]
        if len(points) == 1:
            return {"type": "Point", "coordinates": points[0]}
        return {"type": "MultiPoint", "coordinates": points}

    if gtype == "Polygon":
        ring = _normalize_polygon_ring(coords)
        return {"type": "Polygon", "coordinates": [ring]}

    if gtype == "MultiPolygon":
        if not isinstance(coords, (list, tuple)) or not coords:
            raise ValueError("MultiPolygon requires at least one polygon.")
        polygons = []
        for poly in coords:
            ring = _normalize_polygon_ring(poly)
            polygons.append([ring])
        if len(polygons) == 1:
            return {"type": "Polygon", "coordinates": polygons[0]}
        return {"type": "MultiPolygon", "coordinates": polygons}

    if gtype == "GeometryCollection":
        geoms = value.get("geometries")
        if not isinstance(geoms, list) or not geoms:
            return {}
        points: list[list[float]] = []
        polygons: list[list[list[list[float]]]] = []
        for geom in geoms:
            if not isinstance(geom, dict):
                continue
            try:
                normalized = normalize_listing_geometry(geom)
            except ValueError:
                continue
            if not normalized:
                continue
            ntype = normalized["type"]
            if ntype == "Point":
                points.append(normalized["coordinates"])
            elif ntype == "MultiPoint":
                points.extend(normalized["coordinates"])
            elif ntype == "Polygon":
                polygons.append(normalized["coordinates"])
            elif ntype == "MultiPolygon":
                polygons.extend(normalized["coordinates"])
        return combine_listing_parts(points, polygons)

    raise ValueError("geometry must be a Point, MultiPoint, Polygon, or MultiPolygon.")


def combine_listing_parts(
    points: list[list[float]],
    polygons: list[list[list[list[float]]]],
) -> dict:
    """Build the simplest GeoJSON that represents the given parts."""
    has_points = bool(points)
    has_polygons = bool(polygons)
    if not has_points and not has_polygons:
        return {}
    if has_points and not has_polygons:
        if len(points) == 1:
            return {"type": "Point", "coordinates": points[0]}
        return {"type": "MultiPoint", "coordinates": points}
    if has_polygons and not has_points:
        if len(polygons) == 1:
            return {"type": "Polygon", "coordinates": polygons[0]}
        return {"type": "MultiPolygon", "coordinates": polygons}
    geometries: list[dict[str, Any]] = []
    if len(points) == 1:
        geometries.append({"type": "Point", "coordinates": points[0]})
    elif points:
        geometries.append({"type": "MultiPoint", "coordinates": points})
    if len(polygons) == 1:
        geometries.append({"type": "Polygon", "coordinates": polygons[0]})
    elif polygons:
        geometries.append({"type": "MultiPolygon", "coordinates": polygons})
    if len(geometries) == 1:
        return geometries[0]
    return {"type": "GeometryCollection", "geometries": geometries}


def _iter_positions(geometry: dict) -> list[tuple[float, float]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Point":
        return [(float(coords[0]), float(coords[1]))]
    if gtype == "MultiPoint":
        return [(float(c[0]), float(c[1])) for c in coords or [] if isinstance(c, (list, tuple))]
    if gtype == "Polygon":
        return _ring_points(coords)
    if gtype == "MultiPolygon":
        pts: list[tuple[float, float]] = []
        for poly in coords or []:
            pts.extend(_ring_points(poly))
        return pts
    if gtype == "GeometryCollection":
        pts = []
        for geom in geometry.get("geometries") or []:
            if isinstance(geom, dict):
                pts.extend(_iter_positions(geom))
        return pts
    return []


def derive_listing_center_and_bbox(
    geometry: dict, buffer_km: int | None = None
) -> tuple[float | None, float | None, dict]:
    if not geometry:
        return None, None, {}
    gtype = geometry.get("type")
    if gtype in ("Point", "Polygon"):
        return _derive_simple(geometry, buffer_km)

    points = _iter_positions(geometry)
    if not points:
        return None, None, {}
    lngs = [p[0] for p in points]
    lats = [p[1] for p in points]
    west, east = min(lngs), max(lngs)
    south, north = min(lats), max(lats)
    center_lng = sum(lngs) / len(lngs)
    center_lat = sum(lats) / len(lats)
    buffer = float(buffer_km or 0)
    if buffer <= 0 and west == east and south == north:
        return center_lat, center_lng, {
            "west": west - 0.05,
            "south": south - 0.05,
            "east": east + 0.05,
            "north": north + 0.05,
        }
    bbox = _expand_bbox(west, south, east, north, buffer)
    return center_lat, center_lng, bbox


__all__ = [
    "MARKETPLACE_UPLOAD_MAX_FEATURES",
    "clamp_report_buffer_km",
    "combine_listing_parts",
    "derive_listing_center_and_bbox",
    "normalize_listing_geometry",
]
