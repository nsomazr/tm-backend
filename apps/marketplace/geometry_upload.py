"""Extract marketplace Point(s) / Polygon(s) from an uploaded layer file."""

from __future__ import annotations

from typing import Any

from apps.maps.shapefile_utils import parse_upload_content

from .geometry import (
    MARKETPLACE_UPLOAD_MAX_FEATURES,
    combine_listing_parts,
    normalize_listing_geometry,
)


def _collect_parts_from_geom(geom: dict[str, Any] | None) -> tuple[list[list[float]], list]:
    if not geom or not isinstance(geom, dict):
        return [], []
    try:
        normalized = normalize_listing_geometry(geom)
    except ValueError:
        return [], []
    if not normalized:
        return [], []

    points: list[list[float]] = []
    polygons: list = []
    gtype = normalized["type"]
    if gtype == "Point":
        points.append(normalized["coordinates"])
    elif gtype == "MultiPoint":
        points.extend(normalized["coordinates"])
    elif gtype == "Polygon":
        polygons.append(normalized["coordinates"])
    elif gtype == "MultiPolygon":
        polygons.extend(normalized["coordinates"])
    elif gtype == "GeometryCollection":
        for child in normalized.get("geometries") or []:
            p, poly = _collect_parts_from_geom(child)
            points.extend(p)
            polygons.extend(poly)
    return points, polygons


def geometry_from_upload(content: bytes, filename: str) -> dict[str, Any]:
    """
    Parse GeoJSON / shapefile ZIP / .shp and return all Point/Polygon features
    as Point, MultiPoint, Polygon, MultiPolygon, or GeometryCollection.
    """
    features = parse_upload_content(content, filename)
    if not features:
        raise ValueError("Upload contains no readable features.")

    if len(features) > MARKETPLACE_UPLOAD_MAX_FEATURES:
        raise ValueError(
            f"Upload has too many features ({len(features)}). "
            f"Maximum is {MARKETPLACE_UPLOAD_MAX_FEATURES}."
        )

    points: list[list[float]] = []
    polygons: list = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        p, poly = _collect_parts_from_geom(feature.get("geometry"))
        points.extend(p)
        polygons.extend(poly)

    combined = combine_listing_parts(points, polygons)
    if not combined:
        raise ValueError(
            "No Point or Polygon found in the upload. "
            "Use a licence/block outline shapefile or GeoJSON."
        )
    return combined
