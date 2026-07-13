"""Report AOI geometry helpers (Point / Polygon + optional buffer ≤ 20 km)."""

from __future__ import annotations

import math

REPORT_BUFFER_KM_MIN = 0
REPORT_BUFFER_KM_MAX = 20


def clamp_report_buffer_km(value: int | float | None) -> int | None:
    if value is None:
        return None
    try:
        km = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if km <= 0:
        return None
    return max(REPORT_BUFFER_KM_MIN, min(REPORT_BUFFER_KM_MAX, km))


def _expand_bbox(west: float, south: float, east: float, north: float, buffer_km: float) -> dict:
    if buffer_km <= 0:
        return {"west": west, "south": south, "east": east, "north": north}
    mid_lat = (south + north) / 2.0
    deg_lat = buffer_km / 111.0
    cos_lat = max(0.2, math.cos(math.radians(mid_lat)))
    deg_lng = buffer_km / (111.0 * cos_lat)
    return {
        "west": west - deg_lng,
        "south": south - deg_lat,
        "east": east + deg_lng,
        "north": north + deg_lat,
    }


def _ring_points(coordinates) -> list[tuple[float, float]]:
    if not isinstance(coordinates, (list, tuple)) or not coordinates:
        return []
    ring = coordinates[0] if isinstance(coordinates[0], (list, tuple)) else coordinates
    points: list[tuple[float, float]] = []
    for pair in ring:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        points.append((float(pair[0]), float(pair[1])))
    return points


def normalize_report_geometry(value) -> dict:
    """Return a cleaned GeoJSON Point/Polygon dict, or {} when empty."""
    if value in (None, "", {}, []):
        return {}
    if not isinstance(value, dict):
        raise ValueError("geometry must be a GeoJSON object.")

    gtype = value.get("type")
    coords = value.get("coordinates")
    if gtype == "Point":
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            raise ValueError("Point geometry requires [lng, lat] coordinates.")
        lng, lat = float(coords[0]), float(coords[1])
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise ValueError("Point coordinates are out of range.")
        return {"type": "Point", "coordinates": [lng, lat]}

    if gtype == "Polygon":
        points = _ring_points(coords)
        if len(points) < 3:
            raise ValueError("Polygon geometry requires at least 3 vertices.")
        ring = [[lng, lat] for lng, lat in points]
        if ring[0] != ring[-1]:
            ring.append(list(ring[0]))
        if len(ring) < 4:
            raise ValueError("Polygon geometry requires a closed ring.")
        return {"type": "Polygon", "coordinates": [ring]}

    raise ValueError("geometry must be a Point or Polygon.")


def derive_center_and_bbox(geometry: dict, buffer_km: int | None = None) -> tuple[float | None, float | None, dict]:
    """Compute center + bounding box from geometry, expanding by buffer_km when set."""
    if not geometry:
        return None, None, {}

    buffer = float(buffer_km or 0)
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")

    if gtype == "Point":
        lng, lat = float(coords[0]), float(coords[1])
        pad = max(buffer, 0.5) if buffer > 0 else 0.05
        bbox = _expand_bbox(lng, lat, lng, lat, pad if buffer > 0 else 0)
        if buffer <= 0:
            bbox = {
                "west": lng - 0.05,
                "south": lat - 0.05,
                "east": lng + 0.05,
                "north": lat + 0.05,
            }
        else:
            bbox = _expand_bbox(lng, lat, lng, lat, buffer)
        return lat, lng, bbox

    if gtype == "Polygon":
        points = _ring_points(coords)
        if not points:
            return None, None, {}
        lngs = [p[0] for p in points]
        lats = [p[1] for p in points]
        west, east = min(lngs), max(lngs)
        south, north = min(lats), max(lats)
        center_lng = sum(lngs) / len(lngs)
        center_lat = sum(lats) / len(lats)
        bbox = _expand_bbox(west, south, east, north, buffer)
        return center_lat, center_lng, bbox

    return None, None, {}
