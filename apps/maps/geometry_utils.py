"""GeoJSON hit testing for map click / area insights."""

from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def point_hit_km(zoom: int) -> float:
    """Max distance (km) from click to a point feature; scales with map zoom."""
    return min(1.5, max(0.08, (360 / (2 ** (zoom + 3))) * 111 * 0.45))


def line_hit_km(zoom: int) -> float:
    """Max distance (km) from click to a line feature; scales with map zoom."""
    return min(3.0, max(0.12, (360 / (2 ** (zoom + 2.5))) * 111 * 0.45))


def _point_in_ring(lng: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting test for one GeoJSON ring (lng, lat pairs)."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def _distance_point_to_segment_km(
    plat: float,
    plng: float,
    alat: float,
    alng: float,
    blat: float,
    blng: float,
) -> float:
    """Approximate shortest distance from a point to a geographic line segment."""
    lat_scale = max(math.cos(math.radians(plat)), 1e-6)
    ax = (alng - plng) * lat_scale
    ay = alat - plat
    bx = (blng - plng) * lat_scale
    by = blat - plat
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return haversine_km(plat, plng, alat, alng)

    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy + 1e-15)))
    closest_lat = plat + (ay + t * dy)
    closest_lng = plng + (ax + t * dx) / lat_scale
    return haversine_km(plat, plng, closest_lat, closest_lng)


def _distance_to_linestring_km(lat: float, lng: float, coords: list[list[float]]) -> float:
    if len(coords) < 2:
        if coords:
            return haversine_km(lat, lng, coords[0][1], coords[0][0])
        return float("inf")
    return min(
        _distance_point_to_segment_km(
            lat, lng, coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]
        )
        for i in range(len(coords) - 1)
    )


def geometry_bbox(geometry: dict[str, Any] | None) -> tuple[float, float, float, float] | None:
    """Return (min_lat, max_lat, min_lng, max_lng) for any GeoJSON geometry."""
    if not geometry or "coordinates" not in geometry:
        return None

    lngs: list[float] = []
    lats: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if (
                len(node) >= 2
                and isinstance(node[0], (int, float))
                and isinstance(node[1], (int, float))
            ):
                lngs.append(float(node[0]))
                lats.append(float(node[1]))
            else:
                for item in node:
                    walk(item)

    walk(geometry["coordinates"])
    if not lngs:
        return None
    return min(lats), max(lats), min(lngs), max(lngs)


def ring_area_km2(ring: list[list[float]]) -> float:
    """Geodesic area of a GeoJSON ring (lng, lat pairs) on the WGS84 sphere."""
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for i in range(len(ring) - 1):
        lng1, lat1 = math.radians(float(ring[i][0])), math.radians(float(ring[i][1]))
        lng2, lat2 = math.radians(float(ring[i + 1][0])), math.radians(float(ring[i + 1][1]))
        total += (lng2 - lng1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total * (EARTH_RADIUS_KM**2) / 2.0)


def geometry_area_km2(geometry: dict[str, Any] | None) -> float:
    """Total geodesic area for Polygon or MultiPolygon GeoJSON geometries."""
    if not geometry or "type" not in geometry:
        return 0.0

    gtype = geometry["type"]
    coords = geometry.get("coordinates")
    if not coords:
        return 0.0

    if gtype == "Polygon":
        area = ring_area_km2(coords[0])
        for hole in coords[1:]:
            area -= ring_area_km2(hole)
        return max(0.0, area)

    if gtype == "MultiPolygon":
        return sum(
            geometry_area_km2({"type": "Polygon", "coordinates": poly}) for poly in coords
        )

    return 0.0


def bbox_intersects_click(
    bbox: tuple[float, float, float, float],
    lat: float,
    lng: float,
    pad_deg: float,
) -> bool:
    min_lat, max_lat, min_lng, max_lng = bbox
    return (
        min_lat - pad_deg <= lat <= max_lat + pad_deg
        and min_lng - pad_deg <= lng <= max_lng + pad_deg
    )


def point_in_geometry(
    lng: float,
    lat: float,
    geometry: dict[str, Any] | None,
    *,
    zoom: int = 10,
    layer_type: str | None = None,
) -> bool:
    if not geometry or "type" not in geometry:
        return False

    gtype = geometry["type"]
    coords = geometry.get("coordinates")
    if not coords:
        return False

    if gtype == "Point":
        plng, plat = coords[0], coords[1]
        return haversine_km(lat, lng, plat, plng) <= point_hit_km(zoom)

    if gtype == "MultiPoint":
        return any(
            haversine_km(lat, lng, c[1], c[0]) <= point_hit_km(zoom) for c in coords
        )

    if gtype == "LineString":
        return _distance_to_linestring_km(lat, lng, coords) <= line_hit_km(zoom)

    if gtype == "MultiLineString":
        return any(
            _distance_to_linestring_km(lat, lng, line) <= line_hit_km(zoom)
            for line in coords
        )

    if gtype == "Polygon":
        return _point_in_ring(lng, lat, coords[0])

    if gtype == "MultiPolygon":
        return any(_point_in_ring(lng, lat, poly[0]) for poly in coords)

    return False


def feature_contains_click(
    lat: float,
    lng: float,
    geometry: dict[str, Any] | None,
    layer_type: str,
    zoom: int = 10,
) -> bool:
    return point_in_geometry(
        lng,
        lat,
        geometry,
        zoom=zoom,
        layer_type=layer_type,
    )


def distance_geometry_to_point_km(
    lat: float,
    lng: float,
    geometry: dict[str, Any] | None,
) -> float:
    """Shortest distance (km) from a WGS84 point to any GeoJSON geometry."""
    if not geometry or "type" not in geometry:
        return float("inf")

    gtype = geometry["type"]
    coords = geometry.get("coordinates")
    if not coords:
        return float("inf")

    if gtype == "Point":
        return haversine_km(lat, lng, coords[1], coords[0])

    if gtype == "MultiPoint":
        return min(haversine_km(lat, lng, c[1], c[0]) for c in coords)

    if gtype == "LineString":
        return _distance_to_linestring_km(lat, lng, coords)

    if gtype == "MultiLineString":
        return min(_distance_to_linestring_km(lat, lng, line) for line in coords)

    if gtype == "Polygon":
        if _point_in_ring(lng, lat, coords[0]):
            return 0.0
        ring = coords[0]
        if len(ring) < 2:
            return float("inf")
        return min(
            _distance_point_to_segment_km(
                lat, lng, ring[i][1], ring[i][0], ring[i + 1][1], ring[i + 1][0]
            )
            for i in range(len(ring) - 1)
        )

    if gtype == "MultiPolygon":
        return min(
            distance_geometry_to_point_km(lat, lng, {"type": "Polygon", "coordinates": poly})
            for poly in coords
        )

    return float("inf")
