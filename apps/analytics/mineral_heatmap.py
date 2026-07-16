"""Build intersection-weighted heatmap samples and concentration contours."""

from __future__ import annotations

import math
import statistics
from typing import Any

from django.core.cache import cache

from apps.maps.geometry_utils import (
    distance_geometry_to_point_km,
    geometry_bbox,
    haversine_km,
    point_in_geometry,
)
from apps.maps.layer_defaults import GENERAL_MINERAL_SLUG
from apps.maps.models import MapFeature, MapLayer
from apps.maps.models import HEATMAP_WEIGHT_DEFAULT, HEATMAP_WEIGHT_MAX

from .insights import _accessible_features
from .spatial_assign import feature_sample_point, layer_display_color

MAX_HEATMAP_POINTS = 16_000
MAX_GRID_ROWS = 72
MAX_GRID_COLS = 72
POINT_PROX_KM = 0.85
LINE_PROX_KM = 1.0
POLYGON_EDGE_KM = 0.35
STRUCTURE_DECAY_KM = 0.65
POLYGON_POINT_DECAY_KM = 1.6
SITE_SEPARATION_KM = 0.6
MAX_DECAY_SITES = 320
HEATMAP_CACHE_TTL = 60 * 60

BASE_WEIGHTS = {
    "all_three": 1.0,
    "poly_point": 0.84,
    "poly_line": 0.64,
    "point_line": 0.50,
    "polygon": 0.34,
    "point": 0.28,
    "line": 0.22,
}

# Pair-weight tweaks for commodities where polygon+point co-location is especially informative.
MINERAL_PAIR_BIAS: dict[str, dict[str, float]] = {
    "gold": {"poly_point": 0.90, "poly_line": 0.58, "point_line": 0.44},
    "copper": {"poly_point": 0.86, "poly_line": 0.68, "point_line": 0.54},
    "iron": {"poly_point": 0.82, "poly_line": 0.72, "point_line": 0.52},
    "graphite": {"poly_point": 0.80, "poly_line": 0.70, "point_line": 0.56},
}


def _pair_weights(mineral_slug: str) -> dict[str, float]:
    bias = MINERAL_PAIR_BIAS.get((mineral_slug or "").lower(), {})
    return {
        "poly_point": bias.get("poly_point", BASE_WEIGHTS["poly_point"]),
        "poly_line": bias.get("poly_line", BASE_WEIGHTS["poly_line"]),
        "point_line": bias.get("point_line", BASE_WEIGHTS["point_line"]),
    }


def _layers_for_heatmap(layer_ids: list[int]) -> list[MapLayer]:
    """Resolve active layers for an explicit id list (owned + associated allowed)."""
    if not layer_ids:
        return []
    id_set = set(layer_ids)
    matched = list(
        MapLayer.objects.filter(is_active=True, id__in=id_set).select_related("mineral")
    )
    return matched


def _layers_for_mineral_slug(mineral_slug: str, country_code: str = "TZ") -> list[MapLayer]:
    from .mineral_coverage import layers_for_catalog_slug

    layers = layers_for_catalog_slug(mineral_slug, country_code=country_code)
    if layers:
        return layers
    return list(
        MapLayer.objects.filter(
            is_active=True,
            mineral__slug=mineral_slug,
            mineral__country__code=country_code,
        ).select_related("mineral")
    )


def _layer_heatmap_weight(layer: MapLayer) -> int:
    raw = getattr(layer, "heatmap_weight", HEATMAP_WEIGHT_DEFAULT)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = HEATMAP_WEIGHT_DEFAULT
    return max(0, min(HEATMAP_WEIGHT_MAX, value))


def _heatmap_display_color(layers: list[MapLayer]) -> str:
    for layer_type in ("polygon", "point", "line"):
        for layer in layers:
            if layer.layer_type == layer_type:
                return layer_display_color(layer)
    return "#E87722"


def _feature_buckets(
    layers: list[MapLayer],
    user,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    polygons: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []

    for layer in layers:
        weight = _layer_heatmap_weight(layer)
        qs = _accessible_features(user).filter(layer=layer).iterator(chunk_size=256)
        for feature in qs:
            geometry = feature.geometry
            if not geometry or "type" not in geometry:
                lat, lng = feature_sample_point(feature)
                if lat or lng:
                    points.append({"lat": lat, "lng": lng, "weight": weight})
                continue

            gtype = geometry["type"]
            if layer.layer_type == "polygon" or gtype in ("Polygon", "MultiPolygon"):
                if gtype == "MultiPolygon":
                    for coords in geometry.get("coordinates") or []:
                        part = {"type": "Polygon", "coordinates": coords}
                        bbox = geometry_bbox(part)
                        if bbox:
                            polygons.append({"geometry": part, "bbox": bbox, "weight": weight})
                else:
                    bbox = geometry_bbox(geometry)
                    if bbox:
                        polygons.append({"geometry": geometry, "bbox": bbox, "weight": weight})
            elif layer.layer_type == "point" or gtype in ("Point", "MultiPoint"):
                coords = geometry.get("coordinates") or []
                if gtype == "Point":
                    points.append(
                        {"lat": float(coords[1]), "lng": float(coords[0]), "weight": weight}
                    )
                elif gtype == "MultiPoint":
                    for c in coords:
                        points.append(
                            {"lat": float(c[1]), "lng": float(c[0]), "weight": weight}
                        )
            elif layer.layer_type == "line" or gtype in ("LineString", "MultiLineString"):
                if gtype == "MultiLineString":
                    for coords in geometry.get("coordinates") or []:
                        part = {"type": "LineString", "coordinates": coords}
                        bbox = geometry_bbox(part)
                        if bbox:
                            lines.append({"geometry": part, "bbox": bbox, "weight": weight})
                else:
                    bbox = geometry_bbox(geometry)
                    if bbox:
                        lines.append({"geometry": geometry, "bbox": bbox, "weight": weight})

    return polygons, points, lines


def _bbox_pad(
    bbox: tuple[float, float, float, float],
    pad_km: float,
) -> tuple[float, float, float, float]:
    min_lat, max_lat, min_lng, max_lng = bbox
    mid_lat = (min_lat + max_lat) / 2
    pad_lat = pad_km / 111.0
    pad_lng = pad_km / (111.0 * max(0.25, math.cos(math.radians(mid_lat))))
    return min_lat - pad_lat, max_lat + pad_lat, min_lng - pad_lng, max_lng + pad_lng


def _combined_bbox(
    polygons: list[dict[str, Any]],
    points: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> tuple[float, float, float, float] | None:
    min_lat = min_lng = float("inf")
    max_lat = max_lng = float("-inf")
    for item in polygons + lines:
        b = item["bbox"]
        min_lat = min(min_lat, b[0])
        max_lat = max(max_lat, b[1])
        min_lng = min(min_lng, b[2])
        max_lng = max(max_lng, b[3])
    for item in points:
        min_lat = min(min_lat, item["lat"])
        max_lat = max(max_lat, item["lat"])
        min_lng = min(min_lng, item["lng"])
        max_lng = max(max_lng, item["lng"])
    if min_lat == float("inf"):
        return None
    return _bbox_pad((min_lat, max_lat, min_lng, max_lng), 2.5)


def _near_polygon(lat: float, lng: float, item: dict[str, Any]) -> bool:
    geometry = item["geometry"]
    if point_in_geometry(lng, lat, geometry):
        return True
    return distance_geometry_to_point_km(lat, lng, geometry) <= POLYGON_EDGE_KM


def _near_point(lat: float, lng: float, plat: float, plng: float) -> bool:
    return haversine_km(lat, lng, plat, plng) <= POINT_PROX_KM


def _near_line(lat: float, lng: float, item: dict[str, Any]) -> bool:
    return distance_geometry_to_point_km(lat, lng, item["geometry"]) <= LINE_PROX_KM


def _intersection_weight(
    has_polygon: bool,
    has_point: bool,
    has_line: bool,
    *,
    mineral_slug: str,
) -> float:
    pairs = _pair_weights(mineral_slug)
    count = int(has_polygon) + int(has_point) + int(has_line)
    if count >= 3:
        return BASE_WEIGHTS["all_three"]
    if count == 2:
        if has_polygon and has_point:
            return pairs["poly_point"]
        if has_polygon and has_line:
            return pairs["poly_line"]
        if has_point and has_line:
            return pairs["point_line"]
    if has_polygon:
        return BASE_WEIGHTS["polygon"]
    if has_point:
        return BASE_WEIGHTS["point"]
    if has_line:
        return BASE_WEIGHTS["line"]
    return 0.0


def _scaled_intersection_weight(
    poly_w: float | None,
    point_w: float | None,
    line_w: float | None,
    *,
    mineral_slug: str,
) -> float:
    """Class strength (3/2/1) scaled by mean heatmap_weight of contributing layers / 10."""
    class_weight = _intersection_weight(
        poly_w is not None,
        point_w is not None,
        line_w is not None,
        mineral_slug=mineral_slug,
    )
    if class_weight <= 0:
        return 0.0
    contributing = [w for w in (poly_w, point_w, line_w) if w is not None]
    if not contributing:
        return 0.0
    mean_weight = sum(contributing) / len(contributing)
    return class_weight * (mean_weight / float(HEATMAP_WEIGHT_MAX))


def _sum_pairwise_products(weights: list[float]) -> float:
    """Cross-mineral strength without normalization."""
    return sum(
        weights[a] * weights[b]
        for a in range(len(weights))
        for b in range(a + 1, len(weights))
    )


def _row_col_range_for_bbox(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    lats: list[float],
    lngs: list[float],
) -> tuple[int, int, int, int]:
    i_min = i_max = j_min = j_max = None
    for i, lat in enumerate(lats):
        if min_lat <= lat <= max_lat:
            if i_min is None:
                i_min = i
            i_max = i
    for j, lng in enumerate(lngs):
        if min_lng <= lng <= max_lng:
            if j_min is None:
                j_min = j
            j_max = j
    if i_min is None or j_min is None or i_max is None or j_max is None:
        return 0, -1, 0, -1
    return i_min, i_max, j_min, j_max


def _expand_bbox_km(
    bbox: tuple[float, float, float, float],
    pad_km: float,
) -> tuple[float, float, float, float]:
    min_lat, max_lat, min_lng, max_lng = bbox
    mid_lat = (min_lat + max_lat) / 2
    pad_lat = pad_km / 111.0
    pad_lng = pad_km / (111.0 * max(0.25, math.cos(math.radians(mid_lat))))
    return min_lat - pad_lat, max_lat + pad_lat, min_lng - pad_lng, max_lng + pad_lng


def _max_cell_weight(
    grid: list[list[float | None]],
    i: int,
    j: int,
    weight: float,
) -> None:
    current = grid[i][j]
    if current is None or weight > current:
        grid[i][j] = weight


def _grid_axes(
    bbox: tuple[float, float, float, float],
) -> tuple[list[float], list[float]]:
    min_lat, max_lat, min_lng, max_lng = bbox
    width_km = max(0.5, haversine_km(min_lat, min_lng, min_lat, max_lng))
    height_km = max(0.5, haversine_km(min_lat, min_lng, max_lat, min_lng))
    spacing_km = max(0.65, min(2.0, math.sqrt(max(width_km * height_km, 4.0) / 48.0)))

    n_cols = min(MAX_GRID_COLS, max(10, int(math.ceil(width_km / spacing_km)) + 1))
    n_rows = min(MAX_GRID_ROWS, max(10, int(math.ceil(height_km / spacing_km)) + 1))

    lngs = [min_lng + (max_lng - min_lng) * j / (n_cols - 1) for j in range(n_cols)]
    lats = [min_lat + (max_lat - min_lat) * i / (n_rows - 1) for i in range(n_rows)]
    return lats, lngs


def _presence_grids(
    polygons: list[dict[str, Any]],
    points: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    lats: list[float],
    lngs: list[float],
) -> tuple[
    list[list[float | None]],
    list[list[float | None]],
    list[list[float | None]],
]:
    n_rows = len(lats)
    n_cols = len(lngs)
    spacing_km = 0.0
    if n_rows > 1:
        spacing_km = max(spacing_km, haversine_km(lats[0], lngs[0], lats[1], lngs[0]))
    if n_cols > 1:
        spacing_km = max(spacing_km, haversine_km(lats[0], lngs[0], lats[0], lngs[1]))

    poly_w: list[list[float | None]] = [[None] * n_cols for _ in range(n_rows)]
    point_w: list[list[float | None]] = [[None] * n_cols for _ in range(n_rows)]
    line_w: list[list[float | None]] = [[None] * n_cols for _ in range(n_rows)]

    for item in polygons:
        expanded = _expand_bbox_km(item["bbox"], POLYGON_EDGE_KM + spacing_km)
        i0, i1, j0, j1 = _row_col_range_for_bbox(*expanded, lats, lngs)
        if i1 < i0:
            continue
        weight = float(item.get("weight", HEATMAP_WEIGHT_DEFAULT))
        for i in range(i0, i1 + 1):
            lat = lats[i]
            for j in range(j0, j1 + 1):
                lng = lngs[j]
                if _near_polygon(lat, lng, item):
                    _max_cell_weight(poly_w, i, j, weight)

    for item in points:
        plat, plng = item["lat"], item["lng"]
        expanded = _expand_bbox_km((plat, plat, plng, plng), POINT_PROX_KM + spacing_km)
        i0, i1, j0, j1 = _row_col_range_for_bbox(*expanded, lats, lngs)
        if i1 < i0:
            continue
        weight = float(item.get("weight", HEATMAP_WEIGHT_DEFAULT))
        for i in range(i0, i1 + 1):
            lat = lats[i]
            for j in range(j0, j1 + 1):
                lng = lngs[j]
                if _near_point(lat, lng, plat, plng):
                    _max_cell_weight(point_w, i, j, weight)

    for item in lines:
        expanded = _expand_bbox_km(item["bbox"], LINE_PROX_KM + spacing_km)
        i0, i1, j0, j1 = _row_col_range_for_bbox(*expanded, lats, lngs)
        if i1 < i0:
            continue
        weight = float(item.get("weight", HEATMAP_WEIGHT_DEFAULT))
        for i in range(i0, i1 + 1):
            lat = lats[i]
            for j in range(j0, j1 + 1):
                lng = lngs[j]
                if _near_line(lat, lng, item):
                    _max_cell_weight(line_w, i, j, weight)

    return poly_w, point_w, line_w


def _decay_sites(
    raw_grid: list[list[float]],
    structure_grid: list[list[bool]],
    lats: list[float],
    lngs: list[float],
    *,
    preserve_background: bool,
) -> list[list[float]]:
    """Spread discrete intersection peaks with geographic Gaussian decay."""
    candidates = [
        (raw_grid[i][j], i, j, structure_grid[i][j])
        for i in range(len(lats))
        for j in range(len(lngs))
        if raw_grid[i][j] > 0
    ]
    candidates.sort(reverse=True, key=lambda item: item[0])

    sites: list[tuple[float, int, int, bool]] = []
    for strength, i, j, has_structure in candidates:
        lat, lng = lats[i], lngs[j]
        if any(
            haversine_km(lat, lng, lats[si], lngs[sj]) < SITE_SEPARATION_KM
            for _, si, sj, _ in sites
        ):
            continue
        sites.append((strength, i, j, has_structure))
        if len(sites) >= MAX_DECAY_SITES:
            break

    if not sites:
        return raw_grid

    grid = [
        [raw_grid[i][j] * 0.12 if preserve_background else 0.0 for j in range(len(lngs))]
        for i in range(len(lats))
    ]
    for strength, site_i, site_j, has_structure in sites:
        radius_km = STRUCTURE_DECAY_KM if has_structure else POLYGON_POINT_DECAY_KM
        max_distance = radius_km * 3.0
        site_lat, site_lng = lats[site_i], lngs[site_j]
        for i, lat in enumerate(lats):
            if haversine_km(site_lat, site_lng, lat, site_lng) > max_distance:
                continue
            for j, lng in enumerate(lngs):
                distance = haversine_km(site_lat, site_lng, lat, lng)
                if distance > max_distance:
                    continue
                grid[i][j] += strength * math.exp(-((distance / radius_km) ** 2))
    return grid


def _build_analysis_grid(
    bbox: tuple[float, float, float, float],
    polygons: list[dict[str, Any]],
    points: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    mineral_slug: str,
) -> tuple[list[list[float]], list[float], list[float]]:
    lats, lngs = _grid_axes(bbox)
    poly_w, point_w, line_w = _presence_grids(polygons, points, lines, lats, lngs)

    n_rows = len(lats)
    n_cols = len(lngs)
    raw_grid: list[list[float]] = []
    structure_grid: list[list[bool]] = []
    for i in range(n_rows):
        row: list[float] = []
        structure_row: list[bool] = []
        for j in range(n_cols):
            row.append(
                _scaled_intersection_weight(
                    poly_w[i][j],
                    point_w[i][j],
                    line_w[i][j],
                    mineral_slug=mineral_slug,
                )
            )
            present_count = sum(
                value is not None
                for value in (poly_w[i][j], point_w[i][j], line_w[i][j])
            )
            structure_row.append(line_w[i][j] is not None and present_count >= 2)
        raw_grid.append(row)
        structure_grid.append(structure_row)

    has_intersections = any(
        sum(
            value is not None
            for value in (poly_w[i][j], point_w[i][j], line_w[i][j])
        )
        >= 2
        for i in range(len(lats))
        for j in range(len(lngs))
    )
    if not has_intersections:
        return raw_grid, lats, lngs

    intersection_grid = [
        [
            raw_grid[i][j]
            if sum(
                value is not None
                for value in (poly_w[i][j], point_w[i][j], line_w[i][j])
            )
            >= 2
            else 0.0
            for j in range(len(lngs))
        ]
        for i in range(len(lats))
    ]
    decayed_grid = _decay_sites(
        intersection_grid,
        structure_grid,
        lats,
        lngs,
        preserve_background=False,
    )
    # Keep single-layer evidence visible as low background without broadening peaks.
    grid = [
        [
            max(decayed_grid[i][j], raw_grid[i][j] * 0.12)
            for j in range(len(lngs))
        ]
        for i in range(len(lats))
    ]
    return grid, lats, lngs


def _grid_to_points(
    grid: list[list[float]],
    lats: list[float],
    lngs: list[float],
    feature_points: list[dict[str, Any]] | None = None,
) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    seen: set[tuple[float, float]] = set()

    for i, lat in enumerate(lats):
        for j, lng in enumerate(lngs):
            weight = grid[i][j]
            if weight <= 0:
                continue
            key = (round(lat, 5), round(lng, 5))
            if key in seen:
                continue
            seen.add(key)
            points.append(
                {"lat": round(lat, 6), "lng": round(lng, 6), "weight": round(weight, 3)}
            )
            if len(points) >= MAX_HEATMAP_POINTS:
                return points

    for item in feature_points or []:
        plat, plng = item["lat"], item["lng"]
        key = (round(plat, 5), round(plng, 5))
        if key in seen:
            continue
        seen.add(key)
        layer_w = float(item.get("weight", HEATMAP_WEIGHT_DEFAULT))
        points.append(
            {
                "lat": round(plat, 6),
                "lng": round(plng, 6),
                "weight": round(
                    BASE_WEIGHTS["point"] * (layer_w / float(HEATMAP_WEIGHT_MAX)),
                    3,
                ),
            }
        )
        if len(points) >= MAX_HEATMAP_POINTS:
            break

    if len(points) > MAX_HEATMAP_POINTS:
        points.sort(key=lambda item: item["weight"], reverse=True)
        points = points[:MAX_HEATMAP_POINTS]

    return points


def _heatmap_cache_key(
    mineral_slug: str,
    country_code: str,
    layer_ids: list[int] | None,
    user,
) -> str:
    ids = ",".join(str(layer_id) for layer_id in sorted(layer_ids or []))
    if user and getattr(user, "is_authenticated", False):
        if getattr(user, "has_paid_access", False) or getattr(user, "is_admin_user", False):
            user_key = "paid"
        else:
            user_key = f"user:{user.pk}"
    else:
        user_key = "anon"
    return f"mineral_heatmap:v10:{country_code}:{mineral_slug}:{ids}:{user_key}"


def _interaction_cache_key(
    country_code: str,
    layer_ids: list[int],
    user,
) -> str:
    ids = ",".join(str(layer_id) for layer_id in sorted(layer_ids))
    if user and getattr(user, "is_authenticated", False):
        if getattr(user, "has_paid_access", False) or getattr(user, "is_admin_user", False):
            user_key = "paid"
        else:
            user_key = f"user:{user.pk}"
    else:
        user_key = "anon"
    return f"mineral_heatmap:v11:interaction:{country_code}:{ids}:{user_key}"


def _marching_squares_segment(
    v00: float,
    v10: float,
    v11: float,
    v01: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    threshold: float,
) -> list[tuple[float, float]]:
    """Return 0–2 interpolated edge crossings for one cell (lng=x, lat=y)."""
    above = [
        v00 >= threshold,
        v10 >= threshold,
        v11 >= threshold,
        v01 >= threshold,
    ]
    if all(above) or not any(above):
        return []

    def interp(a: float, b: float, ya: float, yb: float) -> float:
        if abs(b - a) < 1e-9:
            return ya
        t = (threshold - a) / (b - a)
        return ya + t * (yb - ya)

    edges: list[tuple[float, float]] = []
    # Top edge (v00–v10)
    if above[0] != above[1]:
        edges.append((interp(v00, v10, x0, x1), y1))
    # Right edge (v10–v11)
    if above[1] != above[2]:
        edges.append((x1, interp(v10, v11, y1, y0)))
    # Bottom edge (v11–v01)
    if above[2] != above[3]:
        edges.append((interp(v11, v01, x0, x1), y0))
    # Left edge (v01–v00)
    if above[3] != above[0]:
        edges.append((x0, interp(v01, v00, y0, y1)))

    if len(edges) == 2:
        return edges
    return []


def _contours_at_threshold(
    grid: list[list[float]],
    lats: list[float],
    lngs: list[float],
    threshold: float,
) -> list[list[list[float]]]:
    """GeoJSON-style paths: each path is [[lng, lat], ...]."""
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    n_rows = len(grid)
    n_cols = len(grid[0]) if grid else 0

    for i in range(n_rows - 1):
        for j in range(n_cols - 1):
            v00 = grid[i + 1][j]
            v10 = grid[i + 1][j + 1]
            v11 = grid[i][j + 1]
            v01 = grid[i][j]
            x0, x1 = lngs[j], lngs[j + 1]
            y0, y1 = lats[i], lats[i + 1]
            pts = _marching_squares_segment(v00, v10, v11, v01, x0, y0, x1, y1, threshold)
            if len(pts) == 2:
                segments.append((pts[0], pts[1]))

    if not segments:
        return []

    # Chain segments into polylines (greedy).
    unused = segments[:]
    paths: list[list[list[float]]] = []

    def key(pt: tuple[float, float]) -> tuple[int, int]:
        return (round(pt[0] * 1e5), round(pt[1] * 1e5))

    while unused:
        a, b = unused.pop(0)
        chain = [a, b]
        changed = True
        while changed:
            changed = False
            for idx in range(len(unused) - 1, -1, -1):
                s, e = unused[idx]
                head = chain[0]
                tail = chain[-1]
                if key(s) == key(tail):
                    chain.append(e)
                    unused.pop(idx)
                    changed = True
                elif key(e) == key(tail):
                    chain.append(s)
                    unused.pop(idx)
                    changed = True
                elif key(e) == key(head):
                    chain.insert(0, s)
                    unused.pop(idx)
                    changed = True
                elif key(s) == key(head):
                    chain.insert(0, e)
                    unused.pop(idx)
                    changed = True
        if len(chain) >= 3:
            paths.append([[pt[0], pt[1]] for pt in chain])
    return paths


def _concentration_contours(
    grid: list[list[float]],
    lats: list[float],
    lngs: list[float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values = [v for row in grid for v in row if v > 0]
    if len(values) < 4:
        return {"mean": 0.0, "median": 0.0, "stdev": 0.0, "cutoff": 0.0}, []

    mean_val = statistics.mean(values)
    median_val = statistics.median(values)
    stdev_val = statistics.pstdev(values)
    cutoff_val = mean_val + (2.0 * stdev_val)
    stats = {
        "mean": round(mean_val, 4),
        "median": round(median_val, 4),
        "stdev": round(stdev_val, 4),
        "cutoff": round(cutoff_val, 4),
    }
    contours: list[dict[str, Any]] = []
    anomaly_paths = _contours_at_threshold(grid, lats, lngs, cutoff_val)
    if anomaly_paths:
        contours.append(
            {
                "level": "anomaly",
                "threshold": round(cutoff_val, 4),
                "coordinates": anomaly_paths,
            },
        )
    return stats, contours


def build_mineral_heatmap(
    mineral_slug: str,
    *,
    country_code: str = "TZ",
    user=None,
    layer_ids: list[int] | None = None,
    locale: str = "en",
) -> dict | None:
    from apps.maps.localization import localized_name

    mineral_slug = (mineral_slug or "").strip()
    if not mineral_slug:
        return None

    cache_key = _heatmap_cache_key(mineral_slug, country_code, layer_ids, user)
    cached = cache.get(cache_key)
    if cached:
        return cached

    if layer_ids:
        mineral_layers = _layers_for_heatmap(layer_ids)
    else:
        mineral_layers = _layers_for_mineral_slug(mineral_slug, country_code)

    if not mineral_layers:
        return None

    owned_slugs = {layer.mineral.slug for layer in mineral_layers if layer.mineral_id}
    bias_slug = mineral_slug if mineral_slug in owned_slugs else next(iter(owned_slugs), mineral_slug)
    if mineral_slug == GENERAL_MINERAL_SLUG and bias_slug != GENERAL_MINERAL_SLUG:
        return None

    color = _heatmap_display_color(mineral_layers)
    slug = mineral_layers[0].slug if bias_slug == GENERAL_MINERAL_SLUG else mineral_slug
    display_name = localized_name(mineral_layers[0], locale)
    for layer in mineral_layers:
        if layer.mineral_id and layer.mineral.slug == mineral_slug:
            display_name = localized_name(layer.mineral, locale)
            color = layer.mineral.color or color
            break

    polygons, points, lines = _feature_buckets(mineral_layers, user)
    if not polygons and not points and not lines:
        return None

    bbox = _combined_bbox(polygons, points, lines)
    if not bbox:
        return None

    grid, lats, lngs = _build_analysis_grid(
        bbox, polygons, points, lines, bias_slug
    )
    points_out = _grid_to_points(grid, lats, lngs, feature_points=points)
    if not points_out:
        return None

    concentration_stats, contours = _concentration_contours(grid, lats, lngs)
    pairs = _pair_weights(bias_slug)

    layer_types_present = {
        t for layer in mineral_layers for t in [layer.layer_type]
    }

    payload = {
        "slug": slug,
        "name": display_name,
        "color": color,
        "mode": "single",
        "feature_count": len(polygons) + len(points) + len(lines),
        "point_count": len(points_out),
        "points": points_out,
        "concentration_stats": concentration_stats,
        "contours": contours,
        "layer_types": sorted(layer_types_present),
        "weight_legend": {
            "strong": BASE_WEIGHTS["all_three"],
            "medium_poly_point": pairs["poly_point"],
            "medium_poly_line": pairs["poly_line"],
            "medium_point_line": pairs["point_line"],
            "light_polygon": BASE_WEIGHTS["polygon"],
            "light_point": BASE_WEIGHTS["point"],
            "light_line": BASE_WEIGHTS["line"],
        },
    }
    cache.set(cache_key, payload, HEATMAP_CACHE_TTL)
    return payload


def _bbox_intersection(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    min_lat = max(a[0], b[0])
    max_lat = min(a[1], b[1])
    min_lng = max(a[2], b[2])
    max_lng = min(a[3], b[3])
    if min_lat >= max_lat or min_lng >= max_lng:
        return None
    return min_lat, max_lat, min_lng, max_lng


def _bbox_intersects(
    item_bbox: tuple[float, float, float, float],
    window: tuple[float, float, float, float],
) -> bool:
    return _bbox_intersection(item_bbox, window) is not None


def _pairwise_overlap_bbox(
    mineral_bboxes: dict[str, tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    """Union of pairwise mineral-bbox intersections (where multi-mineral overlap is possible)."""
    slugs = sorted(mineral_bboxes)
    if len(slugs) < 2:
        return None
    pieces: list[tuple[float, float, float, float]] = []
    for i, slug_a in enumerate(slugs):
        for slug_b in slugs[i + 1 :]:
            overlap = _bbox_intersection(mineral_bboxes[slug_a], mineral_bboxes[slug_b])
            if overlap:
                pieces.append(overlap)
    if not pieces:
        return None
    return (
        min(piece[0] for piece in pieces),
        max(piece[1] for piece in pieces),
        min(piece[2] for piece in pieces),
        max(piece[3] for piece in pieces),
    )


def _filter_buckets_to_bbox(
    polygons: list[dict[str, Any]],
    points: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    window: tuple[float, float, float, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop features outside the analysis window (also filters coordinate outliers)."""
    kept_polygons = [
        item for item in polygons if _bbox_intersects(item["bbox"], window)
    ]
    kept_lines = [item for item in lines if _bbox_intersects(item["bbox"], window)]
    kept_points = [
        item
        for item in points
        if window[0] <= item["lat"] <= window[1] and window[2] <= item["lng"] <= window[3]
    ]
    return kept_polygons, kept_points, kept_lines


def _empty_interaction_payload(
    *,
    minerals: list[dict[str, Any]],
    feature_count: int,
    layer_types: list[str],
    detail: str,
) -> dict[str, Any]:
    return {
        "slug": "multi-mineral-interaction",
        "name": "Multi-mineral interaction",
        "color": "#F97316",
        "mode": "interaction",
        "feature_count": feature_count,
        "point_count": 0,
        "points": [],
        "concentration_stats": None,
        "contours": [],
        "layer_types": layer_types,
        "minerals": minerals,
        "weight_legend": None,
        "empty_reason": "no_overlap",
        "detail": detail,
    }


def build_multi_mineral_interaction_heatmap(
    layer_ids: list[int],
    *,
    country_code: str = "TZ",
    user=None,
    locale: str = "en",
) -> dict | None:
    """Build cross-mineral concentration from summed pairwise weight products."""
    from apps.maps.localization import localized_name

    layer_ids = sorted({int(layer_id) for layer_id in layer_ids if int(layer_id) > 0})
    if not layer_ids:
        return None

    cache_key = _interaction_cache_key(country_code, layer_ids, user)
    cached = cache.get(cache_key)
    if cached:
        return cached

    layers = _layers_for_heatmap(layer_ids)
    grouped_layers: dict[str, list[MapLayer]] = {}
    for layer in layers:
        if not layer.mineral_id or layer.mineral.slug == GENERAL_MINERAL_SLUG:
            continue
        grouped_layers.setdefault(layer.mineral.slug, []).append(layer)
    if len(grouped_layers) < 2:
        return None

    buckets: dict[
        str,
        tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]],
    ] = {}
    mineral_bboxes: dict[str, tuple[float, float, float, float]] = {}
    all_polygons: list[dict[str, Any]] = []
    all_points: list[dict[str, Any]] = []
    all_lines: list[dict[str, Any]] = []
    for slug, mineral_layers in grouped_layers.items():
        mineral_buckets = _feature_buckets(mineral_layers, user)
        buckets[slug] = mineral_buckets
        all_polygons.extend(mineral_buckets[0])
        all_points.extend(mineral_buckets[1])
        all_lines.extend(mineral_buckets[2])
        mineral_bbox = _combined_bbox(*mineral_buckets)
        if mineral_bbox:
            mineral_bboxes[slug] = mineral_bbox

    minerals_meta = []
    for slug in sorted(grouped_layers):
        mineral = grouped_layers[slug][0].mineral
        minerals_meta.append(
            {
                "slug": slug,
                "name": localized_name(mineral, locale),
                "color": mineral.color or _heatmap_display_color(grouped_layers[slug]),
            }
        )
    layer_types = sorted({layer.layer_type for layer in layers})
    feature_count = len(all_polygons) + len(all_points) + len(all_lines)
    empty_detail = (
        "No overlapping concentration for the selected minerals. "
        "Multi-mineral heatmap only shows where two or more minerals share the same area."
    )

    bbox = _pairwise_overlap_bbox(mineral_bboxes)
    if not bbox:
        payload = _empty_interaction_payload(
            minerals=minerals_meta,
            feature_count=feature_count,
            layer_types=layer_types,
            detail=empty_detail,
        )
        cache.set(cache_key, payload, HEATMAP_CACHE_TTL)
        return payload

    # Focus the grid on possible overlap and ignore out-of-window / outlier geometries.
    filtered_buckets: dict[
        str,
        tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]],
    ] = {}
    for slug, mineral_buckets in buckets.items():
        filtered_buckets[slug] = _filter_buckets_to_bbox(
            mineral_buckets[0],
            mineral_buckets[1],
            mineral_buckets[2],
            bbox,
        )

    lats, lngs = _grid_axes(bbox)
    presence: dict[
        str,
        tuple[
            list[list[float | None]],
            list[list[float | None]],
            list[list[float | None]],
        ],
    ] = {}
    for slug, (polygons, points, lines) in filtered_buckets.items():
        presence[slug] = _presence_grids(polygons, points, lines, lats, lngs)

    slugs = sorted(presence)
    raw_grid: list[list[float]] = []
    structure_grid: list[list[bool]] = []
    for i in range(len(lats)):
        row: list[float] = []
        structure_row: list[bool] = []
        for j in range(len(lngs)):
            mineral_weights: dict[str, float] = {}
            structure_slugs: set[str] = set()
            for slug in slugs:
                poly_w, point_w, line_w = presence[slug]
                values = [
                    value
                    for value in (poly_w[i][j], point_w[i][j], line_w[i][j])
                    if value is not None and value > 0
                ]
                if not values:
                    continue
                mineral_weights[slug] = max(values)
                if line_w[i][j] is not None and line_w[i][j] > 0:
                    structure_slugs.add(slug)

            present_slugs = sorted(mineral_weights)
            strength = _sum_pairwise_products(
                [mineral_weights[slug] for slug in present_slugs]
            )
            row.append(strength)
            structure_row.append(
                strength > 0 and any(slug in structure_slugs for slug in present_slugs)
            )
        raw_grid.append(row)
        structure_grid.append(structure_row)

    if not any(value > 0 for row in raw_grid for value in row):
        payload = _empty_interaction_payload(
            minerals=minerals_meta,
            feature_count=feature_count,
            layer_types=layer_types,
            detail=empty_detail,
        )
        cache.set(cache_key, payload, HEATMAP_CACHE_TTL)
        return payload

    grid = _decay_sites(
        raw_grid,
        structure_grid,
        lats,
        lngs,
        preserve_background=False,
    )
    points_out = _grid_to_points(grid, lats, lngs)
    if not points_out:
        payload = _empty_interaction_payload(
            minerals=minerals_meta,
            feature_count=feature_count,
            layer_types=layer_types,
            detail=empty_detail,
        )
        cache.set(cache_key, payload, HEATMAP_CACHE_TTL)
        return payload

    concentration_stats, contours = _concentration_contours(grid, lats, lngs)

    payload = {
        "slug": "multi-mineral-interaction",
        "name": "Multi-mineral interaction",
        "color": "#F97316",
        "mode": "interaction",
        "feature_count": feature_count,
        "point_count": len(points_out),
        "points": points_out,
        "concentration_stats": concentration_stats,
        "contours": contours,
        "layer_types": layer_types,
        "minerals": minerals_meta,
        "weight_legend": None,
    }
    cache.set(cache_key, payload, HEATMAP_CACHE_TTL)
    return payload
