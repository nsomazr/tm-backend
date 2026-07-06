"""Reproject GeoJSON geometries to WGS84 (EPSG:4326) for map display."""

from __future__ import annotations

from typing import Any

from pyproj import Transformer

# Common Tanzania projected CRS when .prj is missing.
_TANZANIA_FALLBACK_CRS = "EPSG:21036"  # Arc 1960 / UTM zone 36S


def _coord_pairs(coords: Any) -> list[tuple[float, float]]:
    if not coords:
        return []
    if isinstance(coords[0], (int, float)):
        return [(float(coords[0]), float(coords[1]))]
    pairs: list[tuple[float, float]] = []
    for part in coords:
        pairs.extend(_coord_pairs(part))
    return pairs


def geometry_needs_reprojection(geometry: dict[str, Any] | None) -> bool:
    if not geometry:
        return False
    for x, y in _coord_pairs(geometry.get("coordinates")):
        if abs(x) > 180 or abs(y) > 90:
            return True
    return False


def _transform_nested(coords: Any, transformer: Transformer) -> Any:
    if isinstance(coords[0], (int, float)):
        lng, lat = transformer.transform(float(coords[0]), float(coords[1]))
        return [lng, lat]
    return [_transform_nested(part, transformer) for part in coords]


def reproject_geometry(
    geometry: dict[str, Any],
    source_crs: str,
    target_crs: str = "EPSG:4326",
) -> dict[str, Any]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not gtype or not coords:
        return geometry
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    return {"type": gtype, "coordinates": _transform_nested(coords, transformer)}


def ensure_wgs84_geometry(
    geometry: dict[str, Any] | None,
    *,
    source_wkt: str | None = None,
    source_epsg: str | None = None,
) -> dict[str, Any] | None:
    if not geometry or not geometry_needs_reprojection(geometry):
        return geometry
    source = source_wkt or source_epsg or _TANZANIA_FALLBACK_CRS
    return reproject_geometry(geometry, source)
