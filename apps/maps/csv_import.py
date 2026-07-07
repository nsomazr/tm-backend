"""Parse coordinate CSV files into GeoJSON-like feature dicts."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

_LAT_COLUMNS = frozenset({"latitude", "lat", "y"})
_LNG_COLUMNS = frozenset({"longitude", "lng", "lon", "long", "x"})
_LABEL_COLUMNS = frozenset({"name", "label", "title"})
_GROUP_COLUMNS = frozenset({"feature_id", "group", "group_id", "fid"})
_GEOMETRY_COLUMNS = frozenset({"wkt", "geometry"})
_GEOJSON_COLUMNS = frozenset({"geojson", "geom_json"})
_VERTICES_COLUMNS = frozenset({"vertices", "coordinates", "coords"})

_RESERVED_COLUMNS = (
    _LAT_COLUMNS
    | _LNG_COLUMNS
    | _LABEL_COLUMNS
    | _GROUP_COLUMNS
    | _GEOMETRY_COLUMNS
    | _GEOJSON_COLUMNS
    | _VERTICES_COLUMNS
)


def csv_bytes_to_features(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig").strip()
    if not text:
        raise ValueError("CSV file is empty.")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV must include a header row.")

    column_map = _build_column_map(reader.fieldnames)
    rows = list(reader)
    if not rows:
        raise ValueError("CSV contains no data rows.")

    if column_map["wkt"] or column_map["geojson"] or column_map["vertices"]:
        return _features_from_geometry_columns(rows, column_map)

    if column_map["lat"] and column_map["lng"]:
        if column_map["group"]:
            return _features_from_grouped_vertices(rows, column_map)
        return _features_from_point_rows(rows, column_map)

    raise ValueError(
        "CSV must include latitude/longitude columns, or wkt/geojson/vertices columns. "
        "For lines or polygons, add a feature_id column to group vertices."
    )


def _normalize_header(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def _build_column_map(fieldnames: list[str]) -> dict[str, str | None]:
    normalized = {_normalize_header(name): name for name in fieldnames if name}

    def pick(options: frozenset[str]) -> str | None:
        for key in options:
            if key in normalized:
                return normalized[key]
        return None

    return {
        "lat": pick(_LAT_COLUMNS),
        "lng": pick(_LNG_COLUMNS),
        "group": pick(_GROUP_COLUMNS),
        "label": pick(_LABEL_COLUMNS),
        "wkt": pick(_GEOMETRY_COLUMNS),
        "geojson": pick(_GEOJSON_COLUMNS),
        "vertices": pick(_VERTICES_COLUMNS),
    }


def _parse_float(value: str | None, field: str) -> float:
    raw = (value or "").strip()
    if not raw:
        raise ValueError(f"Missing {field}.")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: {raw!r}.") from exc


def _row_label(row: dict[str, str], label_col: str | None) -> str:
    if not label_col:
        return ""
    return str(row.get(label_col, "") or "").strip()[:255]


def _row_properties(row: dict[str, str], column_map: dict[str, str | None]) -> dict[str, Any]:
    reserved = {
        column_map["lat"],
        column_map["lng"],
        column_map["group"],
        column_map["label"],
        column_map["wkt"],
        column_map["geojson"],
        column_map["vertices"],
    }
    props: dict[str, Any] = {}
    for key, value in row.items():
        if key in reserved or value in (None, ""):
            continue
        props[key] = value
    label = _row_label(row, column_map["label"])
    if label:
        props.setdefault("name", label)
    return props


def _features_from_point_rows(
    rows: list[dict[str, str]],
    column_map: dict[str, str | None],
) -> list[dict[str, Any]]:
    lat_col = column_map["lat"]
    lng_col = column_map["lng"]
    assert lat_col and lng_col

    features: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        try:
            lat = _parse_float(row.get(lat_col), "latitude")
            lng = _parse_float(row.get(lng_col), "longitude")
        except ValueError as exc:
            raise ValueError(f"Row {index}: {exc}") from exc
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": _row_properties(row, column_map),
            }
        )

    if not features:
        raise ValueError("CSV contains no point features.")
    return features


def _features_from_grouped_vertices(
    rows: list[dict[str, str]],
    column_map: dict[str, str | None],
) -> list[dict[str, Any]]:
    lat_col = column_map["lat"]
    lng_col = column_map["lng"]
    group_col = column_map["group"]
    assert lat_col and lng_col and group_col

    groups: dict[str, list[tuple[float, float, dict[str, str]]]] = {}
    order: list[str] = []

    for index, row in enumerate(rows, start=2):
        group_key = (row.get(group_col) or "").strip()
        if not group_key:
            raise ValueError(f"Row {index}: missing {group_col}.")
        try:
            lat = _parse_float(row.get(lat_col), "latitude")
            lng = _parse_float(row.get(lng_col), "longitude")
        except ValueError as exc:
            raise ValueError(f"Row {index}: {exc}") from exc
        if group_key not in groups:
            groups[group_key] = []
            order.append(group_key)
        groups[group_key].append((lng, lat, row))

    features: list[dict[str, Any]] = []
    for group_key in order:
        vertices = groups[group_key]
        coords = [[lng, lat] for lng, lat, _row in vertices]
        props = _row_properties(vertices[0][2], column_map)
        if len(coords) == 1:
            geometry = {"type": "Point", "coordinates": coords[0]}
        elif len(coords) == 2:
            geometry = {"type": "LineString", "coordinates": coords}
        else:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            geometry = {"type": "Polygon", "coordinates": [coords]}
        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    if not features:
        raise ValueError("CSV contains no grouped features.")
    return features


def _features_from_geometry_columns(
    rows: list[dict[str, str]],
    column_map: dict[str, str | None],
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    wkt_col = column_map["wkt"]
    geojson_col = column_map["geojson"]
    vertices_col = column_map["vertices"]

    for index, row in enumerate(rows, start=2):
        geometry: dict[str, Any] | None = None
        if wkt_col:
            raw = (row.get(wkt_col) or "").strip()
            if raw:
                geometry = _parse_wkt(raw)
        if geometry is None and geojson_col:
            raw = (row.get(geojson_col) or "").strip()
            if raw:
                geometry = _parse_geojson_geometry(raw, index)
        if geometry is None and vertices_col:
            raw = (row.get(vertices_col) or "").strip()
            if raw:
                geometry = _parse_vertices_geometry(raw, index)

        if not geometry:
            continue

        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": _row_properties(row, column_map),
            }
        )

    if not features:
        raise ValueError("CSV contains no features with geometry values.")
    return features


def _parse_geojson_geometry(raw: str, row_number: int) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Row {row_number}: invalid geojson JSON.") from exc
    if not isinstance(data, dict) or "type" not in data or "coordinates" not in data:
        raise ValueError(f"Row {row_number}: geojson must be a GeoJSON geometry object.")
    return data


def _parse_vertices_geometry(raw: str, row_number: int) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Row {row_number}: invalid vertices JSON.") from exc
    if not isinstance(data, list) or len(data) < 1:
        raise ValueError(f"Row {row_number}: vertices must be a JSON coordinate array.")

    coords: list[list[float]] = []
    for pair in data:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            raise ValueError(f"Row {row_number}: each vertex must be [lng, lat].")
        coords.append([float(pair[0]), float(pair[1])])

    if len(coords) == 1:
        return {"type": "Point", "coordinates": coords[0]}
    if len(coords) == 2:
        return {"type": "LineString", "coordinates": coords}
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def _parse_wkt(raw: str) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", raw.strip())
    upper = text.upper()

    point_match = re.match(r"^POINT\s*\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)$", text, re.I)
    if point_match:
        lng, lat = float(point_match.group(1)), float(point_match.group(2))
        return {"type": "Point", "coordinates": [lng, lat]}

    if upper.startswith("LINESTRING"):
        coords = _parse_wkt_coordinate_list(text)
        if len(coords) < 2:
            raise ValueError("LINESTRING requires at least two coordinates.")
        return {"type": "LineString", "coordinates": coords}

    if upper.startswith("POLYGON"):
        rings = _parse_wkt_polygon_rings(text)
        if not rings or len(rings[0]) < 4:
            raise ValueError("POLYGON requires at least three unique vertices.")
        return {"type": "Polygon", "coordinates": rings}

    raise ValueError(f"Unsupported WKT geometry: {raw[:80]}")


def _parse_wkt_coordinate_list(text: str) -> list[list[float]]:
    start = text.find("(")
    end = text.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("Invalid WKT coordinate list.")
    body = text[start + 1 : end].strip()
    if not body:
        return []
    coords: list[list[float]] = []
    for part in body.split(","):
        nums = part.strip().split()
        if len(nums) < 2:
            continue
        coords.append([float(nums[0]), float(nums[1])])
    return coords


def _parse_wkt_polygon_rings(text: str) -> list[list[list[float]]]:
    start = text.find("((")
    end = text.rfind("))")
    if start < 0 or end <= start:
        raise ValueError("Invalid POLYGON WKT.")
    body = text[start + 2 : end]
    ring = _parse_wkt_coordinate_list(f"({body})")
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return [ring]
