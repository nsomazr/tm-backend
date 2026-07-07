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

from .insights import _accessible_features
from .spatial_assign import feature_sample_point, layer_display_color

MAX_HEATMAP_POINTS = 16_000
MAX_GRID_ROWS = 72
MAX_GRID_COLS = 72
POINT_PROX_KM = 0.85
LINE_PROX_KM = 1.0
POLYGON_EDGE_KM = 0.35
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
    if not layer_ids:
        return []
    id_set = set(layer_ids)
    matched = list(
        MapLayer.objects.filter(is_active=True, id__in=id_set).select_related("mineral")
    )
    if not matched:
        return []
    mineral_slugs = {layer.mineral.slug for layer in matched}
    if len(mineral_slugs) != 1:
        return []
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


def _heatmap_display_color(layers: list[MapLayer]) -> str:
    for layer_type in ("polygon", "point", "line"):
        for layer in layers:
            if layer.layer_type == layer_type:
                return layer_display_color(layer)
    return "#E87722"


def _feature_buckets(
    layers: list[MapLayer],
    user,
) -> tuple[list[dict[str, Any]], list[tuple[float, float]], list[dict[str, Any]]]:
    polygons: list[dict[str, Any]] = []
    points: list[tuple[float, float]] = []
    lines: list[dict[str, Any]] = []

    for layer in layers:
        qs = _accessible_features(user).filter(layer=layer).iterator(chunk_size=256)
        for feature in qs:
            geometry = feature.geometry
            if not geometry or "type" not in geometry:
                lat, lng = feature_sample_point(feature)
                if lat or lng:
                    points.append((lat, lng))
                continue

            gtype = geometry["type"]
            if layer.layer_type == "polygon" or gtype in ("Polygon", "MultiPolygon"):
                bbox = geometry_bbox(geometry)
                if bbox:
                    polygons.append({"geometry": geometry, "bbox": bbox})
            elif layer.layer_type == "point" or gtype in ("Point", "MultiPoint"):
                coords = geometry.get("coordinates") or []
                if gtype == "Point":
                    points.append((float(coords[1]), float(coords[0])))
                elif gtype == "MultiPoint":
                    for c in coords:
                        points.append((float(c[1]), float(c[0])))
            elif layer.layer_type == "line" or gtype in ("LineString", "MultiLineString"):
                bbox = geometry_bbox(geometry)
                if bbox:
                    lines.append({"geometry": geometry, "bbox": bbox})

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
    points: list[tuple[float, float]],
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
    for lat, lng in points:
        min_lat = min(min_lat, lat)
        max_lat = max(max_lat, lat)
        min_lng = min(min_lng, lng)
        max_lng = max(max_lng, lng)
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


def _build_analysis_grid(
    bbox: tuple[float, float, float, float],
    polygons: list[dict[str, Any]],
    points: list[tuple[float, float]],
    lines: list[dict[str, Any]],
    mineral_slug: str,
) -> tuple[list[list[float]], list[float], list[float]]:
    min_lat, max_lat, min_lng, max_lng = bbox
    width_km = max(0.5, haversine_km(min_lat, min_lng, min_lat, max_lng))
    height_km = max(0.5, haversine_km(min_lat, min_lng, max_lat, min_lng))
    spacing_km = max(0.65, min(2.0, math.sqrt(max(width_km * height_km, 4.0) / 48.0)))

    n_cols = min(MAX_GRID_COLS, max(10, int(math.ceil(width_km / spacing_km)) + 1))
    n_rows = min(MAX_GRID_ROWS, max(10, int(math.ceil(height_km / spacing_km)) + 1))

    lngs = [min_lng + (max_lng - min_lng) * j / (n_cols - 1) for j in range(n_cols)]
    lats = [min_lat + (max_lat - min_lat) * i / (n_rows - 1) for i in range(n_rows)]

    poly_hit = [[False] * n_cols for _ in range(n_rows)]
    point_hit = [[False] * n_cols for _ in range(n_rows)]
    line_hit = [[False] * n_cols for _ in range(n_rows)]

    for item in polygons:
        expanded = _expand_bbox_km(item["bbox"], POLYGON_EDGE_KM + spacing_km)
        i0, i1, j0, j1 = _row_col_range_for_bbox(*expanded, lats, lngs)
        if i1 < i0:
            continue
        for i in range(i0, i1 + 1):
            lat = lats[i]
            for j in range(j0, j1 + 1):
                lng = lngs[j]
                if _near_polygon(lat, lng, item):
                    poly_hit[i][j] = True

    for plat, plng in points:
        expanded = _expand_bbox_km((plat, plat, plng, plng), POINT_PROX_KM + spacing_km)
        i0, i1, j0, j1 = _row_col_range_for_bbox(*expanded, lats, lngs)
        if i1 < i0:
            continue
        for i in range(i0, i1 + 1):
            lat = lats[i]
            for j in range(j0, j1 + 1):
                lng = lngs[j]
                if _near_point(lat, lng, plat, plng):
                    point_hit[i][j] = True

    for item in lines:
        expanded = _expand_bbox_km(item["bbox"], LINE_PROX_KM + spacing_km)
        i0, i1, j0, j1 = _row_col_range_for_bbox(*expanded, lats, lngs)
        if i1 < i0:
            continue
        for i in range(i0, i1 + 1):
            lat = lats[i]
            for j in range(j0, j1 + 1):
                lng = lngs[j]
                if _near_line(lat, lng, item):
                    line_hit[i][j] = True

    grid: list[list[float]] = []
    for i in range(n_rows):
        row: list[float] = []
        for j in range(n_cols):
            row.append(
                _intersection_weight(
                    poly_hit[i][j],
                    point_hit[i][j],
                    line_hit[i][j],
                    mineral_slug=mineral_slug,
                )
            )
        grid.append(row)

    return grid, lats, lngs


def _grid_to_points(
    grid: list[list[float]],
    lats: list[float],
    lngs: list[float],
    feature_points: list[tuple[float, float]] | None = None,
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

    for plat, plng in feature_points or []:
        key = (round(plat, 5), round(plng, 5))
        if key in seen:
            continue
        seen.add(key)
        points.append(
            {
                "lat": round(plat, 6),
                "lng": round(plng, 6),
                "weight": round(BASE_WEIGHTS["point"], 3),
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
    return f"mineral_heatmap:v7:{country_code}:{mineral_slug}:{ids}:{user_key}"


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


def _circle_for_cluster(
    cluster: list[tuple[int, int, float]],
    lats: list[float],
    lngs: list[float],
) -> dict[str, Any] | None:
    if len(cluster) < 2:
        return None

    cells: list[tuple[float, float, float]] = [
        (lats[i], lngs[j], weight) for i, j, weight in cluster
    ]
    total = sum(weight for _, _, weight in cells)
    center_lat = sum(lat * weight for lat, _, weight in cells) / total
    center_lng = sum(lng * weight for _, lng, weight in cells) / total
    distances = sorted(
        haversine_km(center_lat, center_lng, lat, lng) for lat, lng, _ in cells
    )
    idx = min(len(distances) - 1, max(0, int(len(distances) * 0.82)))
    radius_km = distances[idx]
    radius_km = min(16.0, max(0.45, radius_km * 1.12))
    return {
        "center": {"lat": round(center_lat, 6), "lng": round(center_lng, 6)},
        "radius_km": round(radius_km, 3),
    }


def _grid_clusters(
    grid: list[list[float]],
    threshold: float,
    *,
    min_cells: int = 2,
) -> list[list[tuple[int, int, float]]]:
    n_rows = len(grid)
    n_cols = len(grid[0]) if grid else 0
    visited = [[False] * n_cols for _ in range(n_rows)]
    clusters: list[list[tuple[int, int, float]]] = []

    for i in range(n_rows):
        for j in range(n_cols):
            if visited[i][j] or grid[i][j] < threshold:
                continue
            stack = [(i, j)]
            cluster: list[tuple[int, int, float]] = []
            visited[i][j] = True
            while stack:
                ci, cj = stack.pop()
                weight = grid[ci][cj]
                if weight < threshold:
                    continue
                cluster.append((ci, cj, weight))
                for ni, nj in ((ci - 1, cj), (ci + 1, cj), (ci, cj - 1), (ci, cj + 1)):
                    if (
                        0 <= ni < n_rows
                        and 0 <= nj < n_cols
                        and not visited[ni][nj]
                        and grid[ni][nj] >= threshold
                    ):
                        visited[ni][nj] = True
                        stack.append((ni, nj))
            if len(cluster) >= min_cells:
                clusters.append(cluster)

    return clusters


def _localized_concentration_circles(
    grid: list[list[float]],
    lats: list[float],
    lngs: list[float],
    mean_val: float,
    median_val: float,
) -> list[dict[str, Any]]:
    """One dashed circle per disconnected high-concentration cluster (not one map-wide ring)."""
    threshold = max(mean_val, median_val)
    clusters = _grid_clusters(grid, threshold, min_cells=2)
    contours: list[dict[str, Any]] = []
    for cluster in clusters:
        circle = _circle_for_cluster(cluster, lats, lngs)
        if not circle:
            continue
        contours.append(
            {
                "level": "concentration",
                "threshold": round(threshold, 4),
                "center": circle["center"],
                "radius_km": circle["radius_km"],
            }
        )
    return contours


def _concentration_contours(
    grid: list[list[float]],
    lats: list[float],
    lngs: list[float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values = [v for row in grid for v in row if v > 0]
    if len(values) < 4:
        return {"mean": 0.0, "median": 0.0}, []

    mean_val = statistics.mean(values)
    median_val = statistics.median(values)
    stats = {"mean": round(mean_val, 4), "median": round(median_val, 4)}
    contours = _localized_concentration_circles(grid, lats, lngs, mean_val, median_val)
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

    only_mineral_slug = next(iter({layer.mineral.slug for layer in mineral_layers}))
    if mineral_slug == GENERAL_MINERAL_SLUG and only_mineral_slug != GENERAL_MINERAL_SLUG:
        return None

    color = _heatmap_display_color(mineral_layers)
    slug = mineral_layers[0].slug if only_mineral_slug == GENERAL_MINERAL_SLUG else only_mineral_slug
    display_name = localized_name(mineral_layers[0], locale)

    polygons, points, lines = _feature_buckets(mineral_layers, user)
    if not polygons and not points and not lines:
        return None

    bbox = _combined_bbox(polygons, points, lines)
    if not bbox:
        return None

    grid, lats, lngs = _build_analysis_grid(
        bbox, polygons, points, lines, only_mineral_slug
    )
    points_out = _grid_to_points(grid, lats, lngs, feature_points=points)
    if not points_out:
        return None

    concentration_stats, contours = _concentration_contours(grid, lats, lngs)
    pairs = _pair_weights(only_mineral_slug)

    layer_types_present = {
        t for layer in mineral_layers for t in [layer.layer_type]
    }

    payload = {
        "slug": slug,
        "name": display_name,
        "color": color,
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
