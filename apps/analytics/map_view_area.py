"""Map view area: default 10 km² circular analysis zone and optional extended area billing."""

from __future__ import annotations

import math

from django.conf import settings

EARTH_RADIUS_KM = 6371.0


def included_analysis_km2() -> float:
    return float(getattr(settings, "AERIAL_INCLUDED_KM2", 10))


def analysis_zone_radius_km(area_km2: float | None = None) -> float:
    """Radius (km) of the circular analysis zone for a given area in km²."""
    area = area_km2 if area_km2 and area_km2 > 0 else included_analysis_km2()
    return math.sqrt(area / math.pi)


def analysis_zone_half_side_km(area_km2: float | None = None) -> float:
    """Alias kept for compatibility; circular zones use radius, not square half-side."""
    return analysis_zone_radius_km(area_km2)


def analysis_zone_deltas_degrees(lat: float, area_km2: float | None = None) -> tuple[float, float]:
    """Lat/lng deltas (degrees) for the circular zone bounding box centered on lat."""
    radius_km = analysis_zone_radius_km(area_km2)
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return lat_delta, lng_delta


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1, lng1, lat2, lng2 = float(lat1), float(lng1), float(lat2), float(lng2)
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def point_in_analysis_zone(
    lat: float,
    lng: float,
    center_lat: float,
    center_lng: float,
    area_km2: float | None = None,
) -> bool:
    radius_km = analysis_zone_radius_km(area_km2)
    return haversine_km(center_lat, center_lng, lat, lng) <= radius_km


def analysis_area_from_viewport_px(
    lat: float,
    zoom: int,
    viewport_width_px: float,
    viewport_height_px: float,
) -> float:
    """Approximate visible map rectangle area from zoom and viewport pixels."""
    zoom = max(3, min(int(zoom), 18))
    lat_rad = math.radians(lat)
    meters_per_pixel = math.cos(lat_rad) * 2 * math.pi * 6378137 / (256 * 2**zoom)
    width_km = (meters_per_pixel * viewport_width_px) / 1000
    height_km = (meters_per_pixel * viewport_height_px) / 1000
    return width_km * height_km


def resolve_extended_area_km2(
    lat: float,
    zoom: int,
    *,
    view_area_km2: float | None = None,
    viewport_width: float | None = None,
    viewport_height: float | None = None,
) -> float | None:
    """Visible map area the user may optionally extend analysis to."""
    if view_area_km2 is not None:
        try:
            area = float(view_area_km2)
        except (TypeError, ValueError):
            area = 0.0
        if area > 0:
            return area

    try:
        width = float(viewport_width) if viewport_width is not None else 0.0
        height = float(viewport_height) if viewport_height is not None else 0.0
    except (TypeError, ValueError):
        width = height = 0.0

    if width > 0 and height > 0:
        return analysis_area_from_viewport_px(lat, zoom, width, height)

    return None


def parse_map_view_params(source) -> dict:
    """Read map view metrics from a DRF request or plain dict."""
    if hasattr(source, "query_params"):
        qp = source.query_params
        body = getattr(source, "data", None)
        if not isinstance(body, dict):
            body = {}

        def getter(key: str):
            val = qp.get(key)
            if val in (None, ""):
                val = body.get(key)
            return val
    else:
        getter = source.get

    view_area = viewport_w = viewport_h = None
    raw_area = getter("view_area_km2")
    if raw_area not in (None, ""):
        try:
            view_area = float(raw_area)
        except (TypeError, ValueError):
            view_area = None

    raw_w = getter("viewport_width")
    raw_h = getter("viewport_height")
    raw_extend = getter("extend_area")
    extend_area = str(raw_extend).lower() in ("1", "true", "yes") if raw_extend not in (None, "") else False
    if raw_w not in (None, ""):
        try:
            viewport_w = float(raw_w)
        except (TypeError, ValueError):
            viewport_w = None
    if raw_h not in (None, ""):
        try:
            viewport_h = float(raw_h)
        except (TypeError, ValueError):
            viewport_h = None

    return {
        "view_area_km2": view_area,
        "viewport_width": viewport_w,
        "viewport_height": viewport_h,
        "extend_area": extend_area,
    }
