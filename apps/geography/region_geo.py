"""Approximate map centers for Tanzania regions (search fly-to and seed bounds)."""

from __future__ import annotations

# lat, lng, default zoom for region search
REGION_CENTERS: dict[str, tuple[float, float, int]] = {
    "Arusha": (-3.3869, 36.6830, 9),
    "Dar es Salaam": (-6.7924, 39.2083, 10),
    "Dodoma": (-6.1630, 35.7516, 9),
    "Geita": (-2.8717, 32.2177, 9),
    "Iringa": (-7.7706, 35.6900, 9),
    "Kagera": (-1.3000, 31.4000, 9),
    "Katavi": (-6.5000, 31.2000, 9),
    "Kigoma": (-4.8762, 29.6265, 9),
    "Kilimanjaro": (-3.0674, 37.3556, 9),
    "Lindi": (-9.9960, 39.7143, 9),
    "Manyara": (-4.0830, 35.8500, 9),
    "Mara": (-1.7750, 34.2250, 9),
    "Mbeya": (-8.9090, 33.4600, 9),
    "Morogoro": (-6.8270, 37.6600, 9),
    "Mtwara": (-10.2660, 40.1830, 9),
    "Mwanza": (-2.5164, 32.9175, 9),
    "Njombe": (-9.3320, 34.7670, 9),
    "Pwani": (-7.5000, 39.0000, 9),
    "Rukwa": (-8.0100, 31.6200, 9),
    "Ruvuma": (-10.6870, 36.2630, 9),
    "Shinyanga": (-3.6639, 33.4211, 9),
    "Simiyu": (-2.8300, 33.9800, 9),
    "Singida": (-4.8160, 34.7430, 9),
    "Songwe": (-8.9000, 33.4500, 9),
    "Tabora": (-5.0160, 32.8000, 9),
    "Tanga": (-5.0689, 39.0988, 9),
    "Zanzibar": (-6.1650, 39.1990, 10),
}


def region_center(name: str) -> dict | None:
    entry = REGION_CENTERS.get(name)
    if not entry:
        return None
    lat, lng, _zoom = entry
    return {"lat": lat, "lng": lng}


def region_zoom(name: str) -> int:
    entry = REGION_CENTERS.get(name)
    return entry[2] if entry else 10


def region_bounds(name: str, delta: float = 0.45) -> dict:
    entry = REGION_CENTERS.get(name)
    if not entry:
        return {}
    lat, lng, _ = entry
    return {
        "west": lng - delta,
        "east": lng + delta,
        "south": lat - delta,
        "north": lat + delta,
    }


def region_at_point(lat: float, lng: float) -> str | None:
    """Best-effort Tanzania admin region for a WGS84 click point."""
    from apps.maps.geometry_utils import haversine_km

    containing: list[tuple[float, str]] = []
    for name, (rlat, rlng, _z) in REGION_CENTERS.items():
        bounds = region_bounds(name)
        if not bounds:
            continue
        if bounds["south"] <= lat <= bounds["north"] and bounds["west"] <= lng <= bounds["east"]:
            containing.append((haversine_km(lat, lng, rlat, rlng), name))

    if containing:
        containing.sort(key=lambda item: item[0])
        return containing[0][1]

    nearest: tuple[float, str] | None = None
    for name, (rlat, rlng, _z) in REGION_CENTERS.items():
        dist = haversine_km(lat, lng, rlat, rlng)
        if nearest is None or dist < nearest[0]:
            nearest = (dist, name)
    if nearest and nearest[0] <= 180:
        return nearest[1]
    return None
