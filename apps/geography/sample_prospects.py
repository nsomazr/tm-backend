"""Regional sample prospect geometries - each layer in a distinct Tanzania location."""

from __future__ import annotations


def _box(lng: float, lat: float, w: float = 0.35, h: float = 0.25) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [lng, lat],
            [lng + w, lat],
            [lng + w, lat + h],
            [lng, lat + h],
            [lng, lat],
        ]],
    }


def _line(lng1: float, lat1: float, lng2: float, lat2: float) -> dict:
    return {
        "type": "LineString",
        "coordinates": [[lng1, lat1], [lng2, lat2]],
    }


# Each layer slug maps to features in a unique region (no shared coordinates across minerals)
SAMPLE_LAYER_FEATURES: dict[str, list[dict]] = {
    "gold-priority-1": [
        {"geometry": _box(32.0, -2.8), "properties": {"name": "Geita Prospect A", "region": "Geita", "mineral": "gold"}},
        {"geometry": _box(32.5, -2.5, 0.3, 0.2), "properties": {"name": "Geita Prospect B", "region": "Geita", "mineral": "gold"}},
    ],
    "gold-priority-2": [
        {"geometry": _box(33.2, -3.6), "properties": {"name": "Shinyanga Belt", "region": "Shinyanga", "mineral": "gold"}},
        {"geometry": _box(33.7, -3.3, 0.28, 0.22), "properties": {"name": "Kahama Zone", "region": "Shinyanga", "mineral": "gold"}},
    ],
    "gold-priority-3": [
        {"geometry": _box(34.0, -1.6), "properties": {"name": "Mara North", "region": "Mara", "mineral": "gold"}},
    ],
    "graphite-zones": [
        {"geometry": _box(38.5, -10.2), "properties": {"name": "Lindi Graphite", "region": "Lindi", "mineral": "graphite"}},
        {"geometry": _box(39.0, -9.8, 0.3, 0.25), "properties": {"name": "Mtwara Graphite", "region": "Mtwara", "mineral": "graphite"}},
    ],
    "tanzanite-zones": [
        {"geometry": _box(36.0, -3.6), "properties": {"name": "Mererani Block", "region": "Manyara", "mineral": "tanzanite"}},
        {"geometry": _box(36.5, -3.2, 0.25, 0.2), "properties": {"name": "Arusha Gem Belt", "region": "Arusha", "mineral": "tanzanite"}},
    ],
    "copper-zones": [
        {"geometry": _box(30.2, -4.9), "properties": {"name": "Kigoma Copper", "region": "Kigoma", "mineral": "copper"}},
        {"geometry": _box(30.8, -4.5, 0.32, 0.24), "properties": {"name": "Lake Tanganyika Zone", "region": "Kigoma", "mineral": "copper"}},
    ],
    "nickel-zones": [
        {"geometry": _box(37.0, -7.2), "properties": {"name": "Morogoro Nickel", "region": "Morogoro", "mineral": "nickel"}},
        {"geometry": _box(37.6, -6.8, 0.3, 0.22), "properties": {"name": "Uluguru Target", "region": "Morogoro", "mineral": "nickel"}},
    ],
    "iron-zones": [
        {"geometry": _box(35.5, -6.2), "properties": {"name": "Dodoma Iron", "region": "Dodoma", "mineral": "iron-ore"}},
        {"geometry": _box(36.0, -5.8, 0.35, 0.28), "properties": {"name": "Central Iron Belt", "region": "Dodoma", "mineral": "iron-ore"}},
    ],
    "lithium-zones": [
        {"geometry": _box(33.0, -8.8), "properties": {"name": "Mbeya Lithium", "region": "Mbeya", "mineral": "lithium"}},
        {"geometry": _box(33.8, -9.2, 0.3, 0.25), "properties": {"name": "Songwe Pegmatite", "region": "Songwe", "mineral": "lithium"}},
    ],
    "main-structures": [
        {"geometry": _line(32.0, -2.85, 32.45, -2.55), "properties": {"name": "Geita Shear", "region": "Geita"}},
        {"geometry": _line(32.55, -2.65, 32.95, -2.35), "properties": {"name": "Geita Fault B", "region": "Geita"}},
        {"geometry": _line(33.25, -3.55, 33.65, -3.15), "properties": {"name": "Lake Zone Fault", "region": "Shinyanga"}},
        {"geometry": _line(34.05, -1.65, 34.45, -1.25), "properties": {"name": "Mara Shear", "region": "Mara"}},
    ],
    "linear-structures": [
        {"geometry": _line(32.1, -2.75, 32.35, -2.62), "properties": {"name": "Geita Trend", "region": "Geita"}},
        {"geometry": _line(33.35, -3.45, 33.55, -3.28), "properties": {"name": "Kahama Trend", "region": "Shinyanga"}},
        {"geometry": _line(36.05, -3.55, 36.35, -3.25), "properties": {"name": "Mererani Trend", "region": "Manyara"}},
    ],
}
