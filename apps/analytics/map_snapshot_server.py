"""Server-rendered map figures when the browser cannot export the live map canvas."""

from __future__ import annotations

import io
import logging
import math
import urllib.request
from typing import Any

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

TILE_SIZE = 256
TILE_URL = "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
USER_AGENT = "TerraMeta-InsightExport/1.0"

DEFAULT_BOUNDS = {"west": 29.34, "south": -11.75, "east": 40.44, "north": -0.99}


def _country_bounds(country_code: str) -> dict[str, float]:
    try:
        from apps.geography.country_geo import COUNTRY_PRESETS

        preset = COUNTRY_PRESETS.get(country_code.upper(), COUNTRY_PRESETS.get("TZ"))
        if preset and preset.get("bounds"):
            return preset["bounds"]
    except Exception:
        pass
    return DEFAULT_BOUNDS


def _fetch_tile(zoom: int, x: int, y: int) -> Image.Image | None:
    n = 2**zoom
    x = x % n
    if y < 0 or y >= n:
        return None
    url = TILE_URL.format(z=zoom, x=x, y=y)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return Image.open(io.BytesIO(resp.read())).convert("RGB")
    except Exception as exc:
        logger.warning("Map tile fetch failed (%s): %s", url, exc)
        return None


def _lat_lng_to_world_px(lat: float, lng: float, zoom: int) -> tuple[float, float]:
    sin_lat = math.sin(math.radians(lat))
    n = 2**zoom
    x = (lng + 180.0) / 360.0 * n * TILE_SIZE
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * n * TILE_SIZE
    return x, y


def _world_px_bounds(
    west: float,
    south: float,
    east: float,
    north: float,
    zoom: int,
) -> tuple[float, float, float, float]:
    nw_x, nw_y = _lat_lng_to_world_px(north, west, zoom)
    se_x, se_y = _lat_lng_to_world_px(south, east, zoom)
    left = min(nw_x, se_x)
    right = max(nw_x, se_x)
    top = min(nw_y, se_y)
    bottom = max(nw_y, se_y)
    return left, top, right, bottom


def _render_world_rect(
    left: float,
    top: float,
    right: float,
    bottom: float,
    zoom: int,
) -> Image.Image:
    width = max(1, int(math.ceil(right - left)))
    height = max(1, int(math.ceil(bottom - top)))
    canvas = Image.new("RGB", (width, height), (236, 240, 244))

    start_x = int(math.floor(left / TILE_SIZE))
    end_x = int(math.floor(right / TILE_SIZE))
    start_y = int(math.floor(top / TILE_SIZE))
    end_y = int(math.floor(bottom / TILE_SIZE))

    for tx in range(start_x, end_x + 1):
        for ty in range(start_y, end_y + 1):
            tile = _fetch_tile(zoom, tx, ty)
            if tile is None:
                continue
            paste_x = int(tx * TILE_SIZE - left)
            paste_y = int(ty * TILE_SIZE - top)
            canvas.paste(tile, (paste_x, paste_y))

    return canvas


def _letterbox(image: Image.Image, out_w: int, out_h: int) -> tuple[Image.Image, float, float, float]:
    scale = min(out_w / image.width, out_h / image.height)
    scaled_w = max(1, int(image.width * scale))
    scaled_h = max(1, int(image.height * scale))
    scaled = image.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (out_w, out_h), (255, 255, 255))
    offset_x = (out_w - scaled_w) / 2
    offset_y = (out_h - scaled_h) / 2
    canvas.paste(scaled, (int(offset_x), int(offset_y)))
    return canvas, scale, offset_x, offset_y


def _load_boundary_features(country_code: str) -> list[dict[str, Any]]:
    try:
        from apps.geography.admin_boundary_service import boundaries_feature_collection
        from apps.geography.country_geo import admin_region_features
        from apps.geography.models import AdminBoundary, Country

        country = Country.objects.filter(code=country_code.upper()).first()
        if country and AdminBoundary.objects.filter(
            country=country,
            source=AdminBoundary.Source.ADMIN_UPLOAD,
        ).exists():
            fc = boundaries_feature_collection(country, [0, 1], display=False)
            return fc.get("features") or []
        return admin_region_features(country_code)
    except Exception as exc:
        logger.warning("Boundary features unavailable for snapshot: %s", exc)
        return []


def _iter_rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return []
    if gtype == "Polygon":
        return [coords[0]]
    if gtype == "MultiPolygon":
        rings: list[list[list[float]]] = []
        for poly in coords:
            if poly and poly[0]:
                rings.append(poly[0])
        return rings
    return []


def _draw_boundaries(
    image: Image.Image,
    features: list[dict[str, Any]],
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    scale: float,
    offset_x: float,
    offset_y: float,
    zoom: int,
) -> None:
    draw = ImageDraw.Draw(image)
    left, top, _, _ = _world_px_bounds(west, south, east, north, zoom)

    def project(lat: float, lng: float) -> tuple[float, float]:
        wx, wy = _lat_lng_to_world_px(lat, lng, zoom)
        return offset_x + (wx - left) * scale, offset_y + (wy - top) * scale

    for feature in features:
        level = int((feature.get("properties") or {}).get("level", 1))
        geometry = feature.get("geometry") or {}
        if level == 0:
            stroke = (15, 118, 110)
            width = 2
        elif level == 1:
            stroke = (55, 65, 81)
            width = 3
        else:
            stroke = (100, 116, 139)
            width = 1
        for ring in _iter_rings(geometry):
            if len(ring) < 2:
                continue
            points = [project(lat, lng) for lng, lat in ring]
            draw.line(points + [points[0]], fill=stroke, width=width)


def _render_country_overview(
    country_code: str,
    out_w: int,
    out_h: int,
) -> tuple[Image.Image | None, dict[str, float], int, float, float, float]:
    bounds = _country_bounds(country_code)
    west, south, east, north = bounds["west"], bounds["south"], bounds["east"], bounds["north"]

    chosen_zoom = 6
    world_img: Image.Image | None = None
    for zoom in range(8, 4, -1):
        left, top, right, bottom = _world_px_bounds(west, south, east, north, zoom)
        world_w = right - left
        world_h = bottom - top
        if world_w < 64 or world_h < 64:
            continue
        if world_w > 2400 or world_h > 2400:
            continue
        chosen_zoom = zoom
        world_img = _render_world_rect(left, top, right, bottom, zoom)
        break

    if world_img is None:
        chosen_zoom = 5
        left, top, right, bottom = _world_px_bounds(west, south, east, north, chosen_zoom)
        world_img = _render_world_rect(left, top, right, bottom, chosen_zoom)

    letterboxed, scale, offset_x, offset_y = _letterbox(world_img, out_w, out_h)
    features = _load_boundary_features(country_code)
    if features:
        _draw_boundaries(
            letterboxed,
            features,
            west=west,
            south=south,
            east=east,
            north=north,
            scale=scale,
            offset_x=offset_x,
            offset_y=offset_y,
            zoom=chosen_zoom,
        )
    return letterboxed, bounds, chosen_zoom, scale, offset_x, offset_y


def _render_map_region(
    lat: float,
    lng: float,
    zoom: int,
    width: int,
    height: int,
) -> Image.Image | None:
    center_x, center_y = _lat_lng_to_world_px(lat, lng, zoom)
    left = center_x - width / 2
    top = center_y - height / 2
    right = left + width
    bottom = top + height
    return _render_world_rect(left, top, right, bottom, zoom)


def _detail_zoom(analysis_area_km2: float | None) -> int:
    km2 = analysis_area_km2 or 50.0
    if km2 <= 30:
        return 13
    if km2 <= 120:
        return 12
    if km2 <= 400:
        return 11
    if km2 <= 1200:
        return 10
    return 9


def _paste_rectangular_inset(
    base: Image.Image,
    detail: Image.Image,
    left: int,
    top: int,
    width: int,
    height: int,
) -> None:
    detail = detail.copy()
    detail.thumbnail((width, height), Image.Resampling.LANCZOS)
    inset = Image.new("RGB", (width, height), (255, 255, 255))
    offset_x = (width - detail.width) // 2
    offset_y = (height - detail.height) // 2
    inset.paste(detail, (offset_x, offset_y))
    base.paste(inset, (left, top))


def _marker_on_overview(
    lat: float,
    lng: float,
    bounds: dict[str, float],
    zoom: int,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> tuple[float, float]:
    west, south, east, north = bounds["west"], bounds["south"], bounds["east"], bounds["north"]
    left, top, _, _ = _world_px_bounds(west, south, east, north, zoom)
    wx, wy = _lat_lng_to_world_px(lat, lng, zoom)
    return offset_x + (wx - left) * scale, offset_y + (wy - top) * scale


def _format_coords_label(lat: float, lng: float) -> str:
    lat_hemi = "N" if lat >= 0 else "S"
    lng_hemi = "E" if lng >= 0 else "W"
    return f"{abs(lat):.5f}°{lat_hemi}, {abs(lng):.5f}°{lng_hemi} · WGS84"


def _draw_coordinate_bar(
    draw: ImageDraw.ImageDraw,
    detail_left: int,
    detail_top: int,
    detail_width: int,
    detail_height: int,
    lat: float,
    lng: float,
) -> None:
    label = _format_coords_label(lat, lng)
    bar_height = 26
    bar_top = detail_top + detail_height - bar_height
    draw.rectangle(
        (detail_left, bar_top, detail_left + detail_width, detail_top + detail_height),
        fill=(255, 255, 255),
        outline=(13, 148, 136),
    )
    draw.line(
        [(detail_left, bar_top), (detail_left + detail_width, bar_top)],
        fill=(13, 148, 136),
        width=1,
    )
    draw.text((detail_left + 10, bar_top + 6), label, fill=(19, 78, 74))


def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
    raw = (hex_color or "").strip().lstrip("#")
    if len(raw) == 6:
        try:
            return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
        except ValueError:
            pass
    return 232, 119, 34


def _analysis_zone_ring(lat: float, lng: float, area_km2: float, segments: int = 72) -> list[tuple[float, float]]:
    from apps.analytics.map_view_area import analysis_zone_radius_km

    radius_km = analysis_zone_radius_km(area_km2)
    lat_rad = math.radians(lat)
    km_per_deg_lat = 111.0
    km_per_deg_lng = 111.0 * max(0.2, math.cos(lat_rad))
    ring: list[tuple[float, float]] = []
    for i in range(segments + 1):
        angle = (2 * math.pi * i) / segments
        north_km = radius_km * math.cos(angle)
        east_km = radius_km * math.sin(angle)
        ring.append((lat + north_km / km_per_deg_lat, lng + east_km / km_per_deg_lng))
    return ring


def _iter_linestrings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return []
    if gtype == "LineString":
        return [coords]
    if gtype == "MultiLineString":
        return list(coords)
    return []


def _iter_points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return []
    if gtype == "Point":
        return [(coords[1], coords[0])]
    if gtype == "MultiPoint":
        return [(pt[1], pt[0]) for pt in coords]
    return []


def _decorate_detail_inset(
    image: Image.Image,
    *,
    center_lat: float,
    center_lng: float,
    zoom: int,
    analysis_area_km2: float | None,
    features: list[Any],
) -> Image.Image:
    """Draw mapped mineral polygons on the magnified inset (inset frame is rectangular)."""
    width, height = image.size
    center_x, center_y = _lat_lng_to_world_px(center_lat, center_lng, zoom)
    left = center_x - width / 2
    top = center_y - height / 2

    def project(lat: float, lng: float) -> tuple[float, float]:
        wx, wy = _lat_lng_to_world_px(lat, lng, zoom)
        return wx - left, wy - top

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for feature in features:
        geometry = getattr(feature, "geometry", None) or {}
        layer = getattr(feature, "layer", None)
        if not geometry or not layer:
            continue
        try:
            from apps.analytics.spatial_assign import layer_display_color

            color = layer_display_color(layer)
        except Exception:
            color = "#E87722"
        r, g, b = _parse_hex_color(color)
        fill = (r, g, b, 132)
        stroke = (r, g, b, 255)

        for ring in _iter_rings(geometry):
            if len(ring) < 3:
                continue
            points = [project(lat, lng) for lng, lat in ring]
            draw.polygon(points, fill=fill, outline=stroke)

        for line in _iter_linestrings(geometry):
            if len(line) < 2:
                continue
            points = [project(lat, lng) for lng, lat in line]
            draw.line(points, fill=stroke, width=2)

        for lat_pt, lng_pt in _iter_points(geometry):
            px, py = project(lat_pt, lng_pt)
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=stroke, outline=(255, 255, 255, 255))

    composed = image.convert("RGBA")
    composed.alpha_composite(overlay)
    return composed.convert("RGB")


def generate_server_map_snapshot(
    lat: float,
    lng: float,
    *,
    analysis_area_km2: float | None = None,
    country_code: str = "TZ",
    user=None,
    feature_ids: list[int] | None = None,
    zoom: int = 12,
) -> bytes | None:
    """Build a callout-style map figure: full country + region borders + magnified inset."""
    try:
        width = 800
        overview_height = 280
        gap = 24
        detail_width = 480
        detail_height = 320
        detail_y = overview_height + gap
        height = detail_y + detail_height + 20

        overview, bounds, overview_zoom, scale, offset_x, offset_y = _render_country_overview(
            country_code,
            width,
            overview_height,
        )
        if overview is None:
            return None

        detail_zoom = _detail_zoom(analysis_area_km2)
        detail = _render_map_region(lat, lng, detail_zoom, 400, 400)
        if detail is None:
            return None

        features: list[Any] = []
        if user is not None:
            try:
                from apps.analytics.insights import features_in_analysis_zone

                features = features_in_analysis_zone(
                    user,
                    lat,
                    lng,
                    zoom,
                    feature_ids=feature_ids,
                    analysis_area_km2=analysis_area_km2,
                )
            except Exception as exc:
                logger.warning("Could not load map features for snapshot: %s", exc)

        detail = _decorate_detail_inset(
            detail,
            center_lat=lat,
            center_lng=lng,
            zoom=detail_zoom,
            analysis_area_km2=analysis_area_km2,
            features=features,
        )

        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        canvas.paste(overview, (0, 0))

        marker_px = _marker_on_overview(
            lat,
            lng,
            bounds,
            overview_zoom,
            scale,
            offset_x,
            offset_y,
        )

        detail_left = (width - detail_width) // 2
        detail_top = detail_y

        draw.polygon(
            [
                marker_px,
                (detail_left + detail_width * 0.18, detail_top),
                (detail_left + detail_width * 0.82, detail_top),
            ],
            fill=(13, 148, 136),
            outline=(13, 148, 136),
        )
        draw.ellipse(
            (marker_px[0] - 9, marker_px[1] - 9, marker_px[0] + 9, marker_px[1] + 9),
            fill=(220, 38, 38),
            outline=(255, 255, 255),
            width=2,
        )

        _paste_rectangular_inset(canvas, detail, detail_left, detail_top, detail_width, detail_height)
        draw.rectangle(
            (detail_left, detail_top, detail_left + detail_width, detail_top + detail_height),
            outline=(13, 148, 136),
            width=3,
        )
        _draw_coordinate_bar(draw, detail_left, detail_top, detail_width, detail_height, lat, lng)

        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=88, optimize=True)
        return out.getvalue()
    except Exception as exc:
        logger.warning("Server map snapshot failed: %s", exc)
        return None
