"""Country focus metadata and simplified boundary geometries."""

from __future__ import annotations

from typing import Any

from .region_geo import REGION_CENTERS, region_bounds

# Simplified Tanzania admin-0 outline (WGS84), Natural Earth–style approximation.
TANZANIA_COUNTRY_RING: list[list[float]] = [
    [29.34, -11.72],
    [29.55, -10.35],
    [29.72, -8.95],
    [30.05, -8.15],
    [30.75, -7.55],
    [31.85, -8.05],
    [32.92, -9.15],
    [33.90, -9.55],
    [34.05, -10.45],
    [34.55, -11.05],
    [35.75, -11.45],
    [37.45, -11.72],
    [38.55, -11.35],
    [39.30, -10.15],
    [39.47, -8.55],
    [39.35, -6.85],
    [39.05, -5.35],
    [38.65, -4.55],
    [37.85, -3.55],
    [37.15, -2.85],
    [36.35, -1.85],
    [35.25, -1.05],
    [34.55, -0.99],
    [33.45, -1.00],
    [32.55, -1.05],
    [31.45, -1.55],
    [30.55, -2.35],
    [30.05, -3.55],
    [29.72, -5.25],
    [29.55, -7.15],
    [29.40, -9.35],
    [29.34, -11.72],
]

COUNTRY_PRESETS: dict[str, dict[str, Any]] = {
    "TZ": {
        "center_lat": -6.5,
        "center_lng": 34.8,
        "default_zoom": 6,
        "bounds": {"west": 29.34, "south": -11.75, "east": 40.44, "north": -0.99},
        "boundary": {
            "type": "Polygon",
            "coordinates": [TANZANIA_COUNTRY_RING],
        },
    },
    "KE": {
        "center_lat": 0.02,
        "center_lng": 37.9,
        "default_zoom": 6,
        "bounds": {"west": 33.9, "south": -4.7, "east": 41.9, "north": 5.0},
        "boundary": {
            "type": "Polygon",
            "coordinates": [
                [
                    [33.9, -4.7],
                    [41.9, -4.7],
                    [41.9, 5.0],
                    [33.9, 5.0],
                    [33.9, -4.7],
                ]
            ],
        },
    },
    "UG": {
        "center_lat": 1.37,
        "center_lng": 32.29,
        "default_zoom": 6,
        "bounds": {"west": 29.5, "south": -1.5, "east": 35.0, "north": 4.23},
        "boundary": {
            "type": "Polygon",
            "coordinates": [
                [
                    [29.5, -1.5],
                    [35.0, -1.5],
                    [35.0, 4.23],
                    [29.5, 4.23],
                    [29.5, -1.5],
                ]
            ],
        },
    },
}


def preset_for_code(code: str) -> dict[str, Any]:
    return COUNTRY_PRESETS.get((code or "").upper(), {})


def _bbox_ring(bounds: dict[str, float]) -> list[list[float]]:
    west = bounds["west"]
    east = bounds["east"]
    south = bounds["south"]
    north = bounds["north"]
    return [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
    ]


def country_boundary_geometry(country) -> dict[str, Any] | None:
    from .models import AdminBoundary

    adm0 = AdminBoundary.objects.filter(
        country=country, level=0, source=AdminBoundary.Source.ADMIN_UPLOAD
    ).first()
    if adm0:
        return adm0.geometry
    if country.boundary:
        return country.boundary
    preset = preset_for_code(country.code)
    return preset.get("boundary")


def country_bounds_dict(country) -> dict[str, float]:
    if country.bounds and country.bounds.get("west") is not None:
        return country.bounds
    preset = preset_for_code(country.code)
    bounds = preset.get("bounds")
    if bounds:
        return bounds
    return {}


def country_center(country) -> tuple[float, float]:
    if country.center_lat is not None and country.center_lng is not None:
        return country.center_lat, country.center_lng
    preset = preset_for_code(country.code)
    if preset:
        return preset["center_lat"], preset["center_lng"]
    return 0.0, 20.0


def country_default_zoom(country) -> int:
    if country.default_zoom:
        return country.default_zoom
    preset = preset_for_code(country.code)
    return preset.get("default_zoom", 6)


def admin_region_features(country_code: str) -> list[dict[str, Any]]:
    """Approximate admin outlines from seeded region bounds (Tanzania)."""
    if country_code.upper() != "TZ":
        return []

    features: list[dict[str, Any]] = []
    for name in REGION_CENTERS:
        bounds = region_bounds(name)
        if not bounds:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"name": name, "kind": "admin"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_bbox_ring(bounds)],
                },
            }
        )
    return features


def country_focus_geojson(country) -> dict[str, Any]:
    from .admin_boundary_service import boundaries_feature_collection
    from .models import AdminBoundary

    if AdminBoundary.objects.filter(
        country=country, source=AdminBoundary.Source.ADMIN_UPLOAD
    ).exists():
        return boundaries_feature_collection(country, [0, 1])

    features: list[dict[str, Any]] = []
    boundary = country_boundary_geometry(country)
    if boundary:
        features.append(
            {
                "type": "Feature",
                "properties": {"name": country.name, "kind": "country"},
                "geometry": boundary,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def country_focus_payload(country) -> dict[str, Any]:
    bounds = country_bounds_dict(country)
    center_lat, center_lng = country_center(country)
    from .models import AdminBoundary

    boundary_levels = sorted(
        {
            level
            for level in AdminBoundary.objects.filter(
                country=country,
                source=AdminBoundary.Source.ADMIN_UPLOAD,
            ).values_list("level", flat=True)
        }
    )
    return {
        "code": country.code,
        "name": country.name,
        "name_sw": country.name_sw,
        "center": {"lat": center_lat, "lng": center_lng},
        "default_zoom": country_default_zoom(country),
        "bounds": bounds,
        "geojson": country_focus_geojson(country),
        "boundary_levels": boundary_levels,
    }


def ensure_country(code: str):
    """Return an active Country row, creating it from the world catalog when missing."""
    from .models import Country
    from .world_countries import WORLD_COUNTRIES

    code = code.upper()
    existing = Country.objects.filter(code=code).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.save(update_fields=["is_active"])
        return existing

    names = dict(WORLD_COUNTRIES)
    if code not in names:
        return None

    preset = preset_for_code(code)
    defaults: dict[str, Any] = {
        "name": names[code],
        "name_sw": names[code],
        "is_active": True,
    }
    if preset:
        defaults.update(
            {
                "center_lat": preset["center_lat"],
                "center_lng": preset["center_lng"],
                "default_zoom": preset["default_zoom"],
                "bounds": preset["bounds"],
                "boundary": preset["boundary"],
            }
        )
    return Country.objects.create(code=code, **defaults)
