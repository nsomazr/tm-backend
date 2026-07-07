"""Elevation and relief context from DEM lookups (Open-Elevation / SRTM)."""

from __future__ import annotations

import logging
import math
import os

import requests
from django.conf import settings
from django.core.cache import cache

from .map_view_area import analysis_zone_radius_km

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60 * 24  # 24 hours
ELEVATION_API_URL = os.getenv(
    "ELEVATION_API_URL",
    getattr(settings, "ELEVATION_API_URL", "https://api.open-elevation.com/api/v1/lookup"),
)


def _cache_key(lat: float, lng: float) -> str:
    return f"terrain-elev:{round(lat, 3)}:{round(lng, 3)}"


def _sample_offsets(radius_km: float, count: int = 8) -> list[tuple[float, float]]:
    """Lat/lng degree offsets for points around the center (~circular)."""
    if radius_km <= 0:
        return [(0.0, 0.0)]
    lat_deg_km = 111.0
    offsets: list[tuple[float, float]] = [(0.0, 0.0)]
    for i in range(count):
        angle = (2 * math.pi * i) / count
        dlat = (radius_km * math.sin(angle)) / lat_deg_km
        dlng = (radius_km * math.cos(angle)) / lat_deg_km
        offsets.append((dlat, dlng))
    return offsets


def _fetch_elevations(locations: list[tuple[float, float]]) -> list[float | None]:
    """Return elevations in metres for each (lat, lng), with per-point cache."""
    results: list[float | None] = [None] * len(locations)
    pending: list[tuple[int, float, float]] = []

    for idx, (lat, lng) in enumerate(locations):
        key = _cache_key(lat, lng)
        cached = cache.get(key)
        if cached is not None:
            results[idx] = float(cached)
        else:
            pending.append((idx, lat, lng))

    if not pending:
        return results

    try:
        payload = {
            "locations": [
                {"latitude": lat, "longitude": lng}
                for _, lat, lng in pending
            ]
        }
        response = requests.post(ELEVATION_API_URL, json=payload, timeout=8)
        response.raise_for_status()
        rows = response.json().get("results") or []
        for (idx, lat, lng), row in zip(pending, rows, strict=False):
            elevation = row.get("elevation")
            if elevation is None:
                continue
            elev = float(elevation)
            results[idx] = elev
            cache.set(_cache_key(lat, lng), elev, CACHE_TTL)
    except Exception as exc:
        logger.warning("Elevation lookup failed: %s", exc)

    return results


def _classify_relief(relief_m: float) -> str:
    if relief_m < 50:
        return "flat"
    if relief_m < 200:
        return "moderate"
    return "rugged"


def _landform_hint(elevation_m: float, relief_m: float, slope_class: str) -> str:
    if elevation_m < 200 and relief_m < 80:
        return "lowland plain"
    if elevation_m > 1500 and relief_m < 150:
        return "highland plateau"
    if relief_m >= 200 or slope_class == "steep":
        return "rugged high-relief terrain"
    if relief_m < 50:
        return "low-relief surface"
    return "moderate-relief hills"


def build_terrain_context(
    lat: float,
    lng: float,
    *,
    analysis_area_km2: float | None = None,
    locale: str = "en",
) -> dict | None:
    radius_km = analysis_zone_radius_km(analysis_area_km2) * 0.85
    offsets = _sample_offsets(radius_km, count=8)
    locations = [(lat + dlat, lng + dlng) for dlat, dlng in offsets]
    elevations = _fetch_elevations(locations)
    valid = [e for e in elevations if e is not None]
    if not valid:
        return None

    center_elev = elevations[0] if elevations[0] is not None else valid[0]
    min_elev = min(valid)
    max_elev = max(valid)
    relief_m = max_elev - min_elev

    # Approximate slope from center vs max difference over radius
    max_diff = max(abs(e - center_elev) for e in valid)
    slope_pct = (max_diff / max(radius_km * 1000, 1)) * 100
    if slope_pct < 3:
        slope_class = "flat"
    elif slope_pct < 10:
        slope_class = "moderate"
    else:
        slope_class = "steep"

    relief_class = _classify_relief(relief_m)
    landform = _landform_hint(center_elev, relief_m, slope_class)

    if locale == "sw":
        summary_lines = [
            f"Mwinuko wa kituo: {center_elev:.0f} m; tofauti ya mwinuko katika eneo la uchambuzi: {relief_m:.0f} m ({relief_class}).",
            f"Muundo wa uso: {landform}; mteremko: {slope_class}.",
            "Vipimo vya mwinuko vinaelezea umbo la uso tu; haviashi kuwa eneo ni bonde la mchanga isipokuwa data ya kijiolojia inathibitisha.",
        ]
    else:
        summary_lines = [
            f"Center elevation: {center_elev:.0f} m; relief across the analysis zone: {relief_m:.0f} m ({relief_class}).",
            f"Surface character: {landform}; slope: {slope_class}.",
            "Elevation metrics describe surface form only; do not equate lowland with sedimentary basin unless geological reference data supports it.",
        ]

    return {
        "elevation_m": round(center_elev, 1),
        "relief_m": round(relief_m, 1),
        "relief_class": relief_class,
        "slope_class": slope_class,
        "landform_hint": landform,
        "min_elevation_m": round(min_elev, 1),
        "max_elevation_m": round(max_elev, 1),
        "summary_lines": summary_lines,
        "ai_block": (
            f"Terrain metrics (SRTM-based):\n"
            f"- Center elevation: {center_elev:.0f} m\n"
            f"- Relief in analysis zone: {relief_m:.0f} m ({relief_class})\n"
            f"- Slope class: {slope_class}\n"
            f"- Landform hint: {landform}\n"
            "Use these only for surface-form context. Do not claim sedimentary basin setting "
            "from elevation alone.\n"
        ),
    }
