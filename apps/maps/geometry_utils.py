"""GeoJSON hit testing for map click / area insights."""

from __future__ import annotations

import math
from typing import Any

# Max distance (km) from click to a point feature to count as a hit.
POINT_HIT_KM = 6.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


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


def point_in_geometry(lng: float, lat: float, geometry: dict[str, Any] | None) -> bool:
    if not geometry or "type" not in geometry:
        return False

    gtype = geometry["type"]
    coords = geometry.get("coordinates")
    if not coords:
        return False

    if gtype == "Point":
        plng, plat = coords[0], coords[1]
        return haversine_km(lat, lng, plat, plng) <= POINT_HIT_KM

    if gtype == "MultiPoint":
        return any(
            haversine_km(lat, lng, c[1], c[0]) <= POINT_HIT_KM for c in coords
        )

    if gtype == "Polygon":
        return _point_in_ring(lng, lat, coords[0])

    if gtype == "MultiPolygon":
        return any(_point_in_ring(lng, lat, poly[0]) for poly in coords)

    # Lines are not treated as mapped area coverage for click insights.
    return False


def feature_contains_click(
    lat: float,
    lng: float,
    geometry: dict[str, Any] | None,
    layer_type: str,
) -> bool:
    if layer_type == "line":
        return False
    if geometry and point_in_geometry(lng, lat, geometry):
        return True
    return False
