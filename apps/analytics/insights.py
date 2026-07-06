"""Location and mineral insight helpers for map search and area queries."""

from collections import defaultdict

import math

from django.db.models import Q

from apps.geography.models import AdminBoundary, Country, Region
from apps.geography.region_geo import region_at_point, region_center, region_zoom
from apps.maps.access import filter_layers_for_user, layers_with_mapped_data, user_has_map_detail_access
from apps.maps.geometry_utils import (
    bbox_intersects_click,
    feature_contains_click,
    geometry_area_km2,
    geometry_bbox,
)
from apps.maps.localization import localized_name
from apps.maps.models import MapFeature, MapLayer
from apps.minerals.models import Mineral

from .map_view_area import analysis_zone_deltas_degrees, included_analysis_km2
from .spatial_assign import (
    AdminBoundaryIndex,
    boundary_center_and_bounds,
    commodities_from_features,
    feature_sample_point,
    features_in_boundary,
)


def _accessible_layers(user):
    qs = MapLayer.objects.filter(is_active=True).select_related("mineral", "region")
    qs = layers_with_mapped_data(qs)
    return filter_layers_for_user(qs, user)


def _accessible_features(user, mineral_slug=None):
    layer_ids = _accessible_layers(user).values_list("id", flat=True)
    qs = MapFeature.objects.filter(
        is_active=True,
        layer_id__in=layer_ids,
    ).select_related("layer", "layer__mineral", "layer__region")
    if mineral_slug:
        qs = qs.filter(layer__mineral__slug=mineral_slug)
    return qs


def _prefilter_delta(zoom: int) -> float:
    """Tight bounding box for DB pre-filter only; geometry test is authoritative."""
    return min(0.2, max(0.025, 360 / (2 ** (zoom + 3))))


def _center_from_bounds(bounds) -> dict | None:
    if not bounds:
        return None
    if isinstance(bounds, dict):
        if bounds.get("type") == "Polygon" and bounds.get("coordinates"):
            coords = bounds["coordinates"][0]
        elif all(k in bounds for k in ("west", "east", "south", "north")):
            return {
                "lat": (float(bounds["south"]) + float(bounds["north"])) / 2,
                "lng": (float(bounds["west"]) + float(bounds["east"])) / 2,
            }
        else:
            coords = bounds.get("coordinates")
            if not coords:
                return None
            if bounds.get("type") == "Polygon":
                coords = coords[0]
        if coords:
            lngs = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            return {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
    return None


def _region_center(region: Region, layer_ids: set) -> dict | None:
    center = _center_from_bounds(region.bounds)
    if center:
        return center
    features = MapFeature.objects.filter(
        is_active=True,
        layer__region=region,
        layer_id__in=layer_ids,
    ).exclude(latitude__isnull=True).exclude(longitude__isnull=True)[:200]
    lats, lngs = [], []
    for feature in features:
        lats.append(float(feature.latitude))
        lngs.append(float(feature.longitude))
    if lats and lngs:
        return {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
    return region_center(region.name)


def _layer_display_color(layer: MapLayer) -> str:
    style = layer.style or {}
    if layer.layer_type == MapLayer.LayerType.LINE:
        return style.get("stroke") or style.get("fill") or "#64748b"
    return style.get("fill") or layer.mineral.color or "#0d9488"


def _features_map_extent(features) -> tuple[dict | None, dict | None]:
    """Center and bounds from feature geometry (polygons, lines, points)."""
    min_lat, max_lat = 90.0, -90.0
    min_lng, max_lng = 180.0, -180.0
    found = False

    for feature in features:
        bbox = geometry_bbox(feature.geometry)
        if bbox:
            b_min_lat, b_max_lat, b_min_lng, b_max_lng = bbox
            min_lat = min(min_lat, b_min_lat)
            max_lat = max(max_lat, b_max_lat)
            min_lng = min(min_lng, b_min_lng)
            max_lng = max(max_lng, b_max_lng)
            found = True
            continue
        if feature.latitude is not None and feature.longitude is not None:
            lat = float(feature.latitude)
            lng = float(feature.longitude)
            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)
            min_lng = min(min_lng, lng)
            max_lng = max(max_lng, lng)
            found = True

    if not found:
        return None, None

    return (
        {"lat": (min_lat + max_lat) / 2, "lng": (min_lng + max_lng) / 2},
        {"west": min_lng, "south": min_lat, "east": max_lng, "north": max_lat},
    )


def _accessible_feature_list(user, limit: int = 2000) -> list[MapFeature]:
    layer_ids = set(_accessible_layers(user).values_list("id", flat=True))
    return list(
        MapFeature.objects.filter(is_active=True, layer_id__in=layer_ids)
        .select_related("layer", "layer__mineral", "layer__region")[:limit]
    )


def _region_stats_for_features(features: list[MapFeature], country_code: str = "TZ") -> list[dict]:
    index = AdminBoundaryIndex(country_code, levels=(AdminBoundary.Level.REGION,))
    counts: dict[str, int] = defaultdict(int)
    areas: dict[str, float] = defaultdict(float)
    for feature in features:
        lat, lng = feature_sample_point(feature)
        name = index.resolve_name(lat, lng)
        if not name and feature.layer.region:
            name = feature.layer.region.name
        if name:
            counts[name] += 1
            if feature.layer.layer_type == MapLayer.LayerType.POLYGON and feature.geometry:
                areas[name] += geometry_area_km2(feature.geometry)
    rows: list[dict] = []
    for name, count in counts.items():
        row: dict = {"region": name, "count": count}
        area = areas.get(name, 0.0)
        if area > 0:
            row["area_km2"] = round(area, 2)
        rows.append(row)
    return sorted(rows, key=lambda row: row["count"], reverse=True)


def _region_counts_for_features(features: list[MapFeature], country_code: str = "TZ") -> list[dict]:
    return _region_stats_for_features(features, country_code)


def _format_region_stat_line(row: dict) -> str:
    area = row.get("area_km2")
    if area and area > 0:
        return f"{row['region']} ({row['count']} zones, {area:.2f} km²)"
    return f"{row['region']} ({row['count']} zones)"


def _apply_polygon_coverage_totals(ctx: dict, features: list, user, locale: str) -> dict:
    commodities = commodities_from_features(
        features,
        locale=locale,
        include_polygon_area=user_has_map_detail_access(user),
    )
    if commodities:
        ctx["minerals"] = commodities
    total_area = sum(float(item.get("area_km2") or 0) for item in ctx.get("minerals") or [])
    if total_area > 0:
        ctx["total_area_km2"] = round(total_area, 2)
    return ctx


def _admin_boundary_search_results(
    q: str,
    user,
    *,
    limit: int = 8,
    country_code: str = "TZ",
) -> list[dict]:
    country = Country.objects.filter(code=country_code.upper()).first()
    if not country:
        return []

    boundaries = (
        AdminBoundary.objects.filter(
            country=country,
            level__in=[
                AdminBoundary.Level.REGION,
                AdminBoundary.Level.DISTRICT,
                AdminBoundary.Level.WARD,
                AdminBoundary.Level.VILLAGE,
            ],
            source=AdminBoundary.Source.ADMIN_UPLOAD,
        )
        .filter(Q(name__icontains=q) | Q(name_sw__icontains=q))
        .select_related("country")
        .order_by("level", "name")[:limit]
    )
    if not boundaries:
        return []

    all_features = _accessible_feature_list(user)
    rows: list[dict] = []
    for boundary in boundaries:
        matched = features_in_boundary(boundary, all_features)
        commodities = commodities_from_features(matched)
        center, bounds = _features_map_extent(matched)
        if not center:
            center, boundary_bounds = boundary_center_and_bounds(boundary)
            if boundary_bounds and not bounds:
                bounds = boundary_bounds

        if boundary.level == AdminBoundary.Level.DISTRICT:
            result_type = "district_boundary"
        elif boundary.level == AdminBoundary.Level.WARD:
            result_type = "ward_boundary"
        elif boundary.level == AdminBoundary.Level.VILLAGE:
            result_type = "village_boundary"
        else:
            result_type = "region_boundary"
        layer_ids_in_region = {feature.layer_id for feature in matched}

        rows.append(
            {
                "type": result_type,
                "id": boundary.id,
                "boundary_id": boundary.id,
                "boundary_level": boundary.level,
                "name": boundary.name,
                "name_sw": boundary.name_sw or "",
                "slug": f"admin-{boundary.level}-{boundary.id}",
                "color": "#64748b",
                "description": boundary.country.name if boundary.country else "",
                "feature_count": len(matched),
                "layer_count": len(layer_ids_in_region),
                "total_layer_count": len(layer_ids_in_region),
                "top_regions": [],
                "top_minerals": commodities[:8],
                "center": center,
                "bounds": bounds,
                "zoom": region_zoom(boundary.name) if boundary.level == 1 else (13 if boundary.level == 4 else (12 if boundary.level == 3 else 11)),
                "has_full_data": user_has_map_detail_access(user),
            }
        )
    return rows


def mineral_search_insights(query: str, user, limit: int = 8) -> list[dict]:
    q = query.strip()
    if not q:
        return []

    layer_ids = set(_accessible_layers(user).values_list("id", flat=True))
    results = []
    seen_names: set[str] = set()

    for row in _admin_boundary_search_results(q, user, limit=limit):
        seen_names.add(row["name"].lower())
        results.append(row)

    if len(results) < limit:
        regions = (
            Region.objects.filter(is_active=True)
            .filter(Q(name__icontains=q) | Q(name_sw__icontains=q))
            .select_related("country")[: limit - len(results)]
        )
        for region in regions:
            if region.name.lower() in seen_names:
                continue
            region_features = MapFeature.objects.filter(
                is_active=True,
                layer__region=region,
                layer_id__in=layer_ids,
            ).select_related("layer__mineral")
            feature_count = region_features.count()

            mineral_counts: dict[str, dict] = {}
            for feature in region_features[:800]:
                mineral = feature.layer.mineral
                if mineral.slug not in mineral_counts:
                    mineral_counts[mineral.slug] = {
                        "slug": mineral.slug,
                        "name": mineral.name,
                        "name_sw": mineral.name_sw,
                        "color": mineral.color,
                        "count": 0,
                    }
                mineral_counts[mineral.slug]["count"] += 1
            top_minerals = sorted(mineral_counts.values(), key=lambda m: m["count"], reverse=True)[:6]

            region_feature_list = list(region_features[:800])
            center, bounds = _features_map_extent(region_feature_list)
            if not center:
                center = _region_center(region, layer_ids)

            seen_names.add(region.name.lower())
            results.append(
                {
                    "type": "region",
                    "id": region.id,
                    "name": region.name,
                    "name_sw": region.name_sw,
                    "slug": f"region-{region.id}",
                    "color": "#64748b",
                    "description": region.country.name if region.country else "",
                    "feature_count": feature_count,
                    "layer_count": MapLayer.objects.filter(
                        region=region, is_active=True, id__in=layer_ids
                    ).count(),
                    "total_layer_count": MapLayer.objects.filter(
                        region=region, is_active=True, id__in=layer_ids
                    ).count(),
                    "top_regions": [],
                    "top_minerals": top_minerals,
                    "center": center,
                    "bounds": bounds,
                    "zoom": region_zoom(region.name) if center else 10,
                    "has_full_data": user_has_map_detail_access(user),
                }
            )

    uploaded_layers = _accessible_layers(user).filter(
        Q(name__icontains=q) | Q(name_sw__icontains=q)
    )[:limit]

    for layer in uploaded_layers:
        name_key = layer.name.lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        features = MapFeature.objects.filter(
            is_active=True,
            layer=layer,
        ).select_related("layer__region")
        feature_count = features.count()
        if feature_count <= 0:
            continue

        feature_list = list(features.select_related("layer__region")[:800])
        top_regions = _region_counts_for_features(feature_list)

        center, bounds = _features_map_extent(feature_list)

        results.append(
            {
                "type": "layer",
                "id": layer.id,
                "name": layer.name,
                "name_sw": layer.name_sw or "",
                "slug": layer.slug,
                "color": _layer_display_color(layer),
                "description": f"Uploaded {layer.layer_type} layer",
                "feature_count": feature_count,
                "layer_count": 1,
                "total_layer_count": 1,
                "top_regions": top_regions,
                "top_minerals": [],
                "center": center,
                "bounds": bounds,
                "zoom": 9,
                "has_full_data": user_has_map_detail_access(user),
            }
        )

    minerals = (
        Mineral.objects.filter(is_active=True)
        .filter(Q(name__icontains=q) | Q(name_sw__icontains=q))
        .distinct()[:limit]
    )

    for mineral in minerals:
        if mineral.name.lower() in seen_names:
            continue
        features = MapFeature.objects.filter(
            is_active=True,
            layer__is_active=True,
            layer__mineral=mineral,
            layer_id__in=layer_ids,
        ).select_related("layer__region")

        feature_count = features.count()
        if feature_count <= 0:
            continue

        feature_list = list(features[:800])
        top_regions = _region_counts_for_features(feature_list)[:5]

        center, bounds = _features_map_extent(feature_list)

        total_layers = _accessible_layers(user).filter(mineral=mineral).count()
        accessible_layer_count = total_layers

        results.append(
            {
                "type": "mineral",
                "id": mineral.id,
                "name": mineral.name,
                "name_sw": mineral.name_sw,
                "slug": mineral.slug,
                "color": mineral.color,
                "description": mineral.description,
                "feature_count": feature_count,
                "layer_count": accessible_layer_count,
                "total_layer_count": total_layers,
                "top_regions": top_regions,
                "top_minerals": [],
                "center": center,
                "bounds": bounds,
                "zoom": 9,
                "has_full_data": user_has_map_detail_access(user),
            }
        )

    return results[:limit]


def mineral_coverage_context(mineral_slug: str, user, locale: str = "en") -> dict | None:
    mineral = None
    try:
        mineral = Mineral.objects.get(slug=mineral_slug, is_active=True)
    except Mineral.DoesNotExist:
        from .mineral_coverage import _find_layer_for_catalog_slug

        layer = _find_layer_for_catalog_slug(
            mineral_slug,
            list(_accessible_layers(user).select_related("mineral", "mineral__country")),
        )
        if layer:
            return layer_coverage_context(layer.id, user, locale=locale)
        return None

    features = list(
        _accessible_features(user, mineral_slug=mineral_slug).select_related(
            "layer", "layer__region", "layer__mineral"
        )[:1200]
    )
    top_regions = _region_stats_for_features(features)[:8]

    lats, lngs = [], []
    for feature in features:
        if feature.latitude and feature.longitude:
            lats.append(float(feature.latitude))
            lngs.append(float(feature.longitude))

    center = None
    if lats and lngs:
        center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}

    top_region = top_regions[0]["region"] if top_regions else None
    count = len(features)

    ctx = {
        "lat": center["lat"] if center else -6.369,
        "lng": center["lng"] if center else 34.888,
        "zoom": 9,
        "region": top_region,
        "minerals": [
            {
                "slug": mineral.slug,
                "name": localized_name(mineral, locale),
                "name_sw": mineral.name_sw,
                "color": mineral.color,
                "count": count,
            }
        ],
        "feature_count": count,
        "labels": [],
        "has_mapped_data": count > 0,
        "search_type": "mineral",
        "search_name": localized_name(mineral, locale),
        "description": mineral.description or "",
        "top_regions": top_regions,
    }
    return _apply_polygon_coverage_totals(ctx, features, user, locale)


def admin_boundary_coverage_context(admin_boundary_id: int, user, locale: str = "en") -> dict | None:
    try:
        boundary = AdminBoundary.objects.select_related("country").get(
            id=admin_boundary_id,
            source=AdminBoundary.Source.ADMIN_UPLOAD,
        )
    except AdminBoundary.DoesNotExist:
        return None

    matched = features_in_boundary(boundary, _accessible_feature_list(user, limit=1200))
    commodities = commodities_from_features(
        matched,
        locale=locale,
        include_polygon_area=user_has_map_detail_access(user),
    )
    center, bounds = _features_map_extent(matched)
    if not center:
        center, boundary_bounds = boundary_center_and_bounds(boundary)
        if boundary_bounds and not bounds:
            bounds = boundary_bounds

    if boundary.level == AdminBoundary.Level.DISTRICT:
        search_type = "district_boundary"
    elif boundary.level == AdminBoundary.Level.WARD:
        search_type = "ward_boundary"
    elif boundary.level == AdminBoundary.Level.VILLAGE:
        search_type = "village_boundary"
    else:
        search_type = "region_boundary"

    return {
        "lat": center["lat"] if center else -6.369,
        "lng": center["lng"] if center else 34.888,
        "zoom": region_zoom(boundary.name) if boundary.level == 1 else (13 if boundary.level == 4 else (12 if boundary.level == 3 else 11)),
        "region": boundary.name,
        "minerals": commodities,
        "feature_count": len(matched),
        "labels": [],
        "has_mapped_data": len(matched) > 0,
        "search_type": search_type,
        "boundary_id": boundary.id,
        "boundary_level": boundary.level,
        "search_name": localized_name(boundary, locale),
        "description": boundary.country.name if boundary.country else "",
        "top_regions": [],
        "top_minerals": commodities[:8],
        "bounds": bounds,
    }


def region_coverage_context(region_id: int, user, locale: str = "en") -> dict | None:
    try:
        region = Region.objects.get(id=region_id, is_active=True)
    except Region.DoesNotExist:
        return None

    layer_ids = set(_accessible_layers(user).values_list("id", flat=True))
    features = list(
        MapFeature.objects.filter(
            is_active=True,
            layer__region=region,
            layer_id__in=layer_ids,
        )
        .select_related("layer__mineral")
        [:1200]
    )

    mineral_counts: dict[str, dict] = {}
    for feature in features:
        mineral = feature.layer.mineral
        if mineral.slug not in mineral_counts:
            mineral_counts[mineral.slug] = {
                "slug": mineral.slug,
                "name": localized_name(mineral, locale),
                "name_sw": mineral.name_sw,
                "color": mineral.color,
                "count": 0,
            }
        mineral_counts[mineral.slug]["count"] += 1

    minerals_list = sorted(mineral_counts.values(), key=lambda m: m["count"], reverse=True)
    center = _region_center(region, layer_ids)
    count = len(features)

    return {
        "lat": center["lat"] if center else -6.369,
        "lng": center["lng"] if center else 34.888,
        "zoom": region_zoom(region.name) if center else 10,
        "region": region.name,
        "minerals": minerals_list,
        "feature_count": count,
        "labels": [],
        "has_mapped_data": count > 0,
        "search_type": "region",
        "search_name": localized_name(region, locale),
        "description": region.country.name if region.country else "",
        "top_regions": [],
        "top_minerals": minerals_list[:8],
    }


def layer_coverage_context(layer_id: int, user, locale: str = "en") -> dict | None:
    try:
        layer = _accessible_layers(user).get(id=layer_id)
    except MapLayer.DoesNotExist:
        return None

    features = list(
        MapFeature.objects.filter(is_active=True, layer=layer).select_related(
            "layer", "layer__region", "layer__mineral"
        )[:1200]
    )
    top_regions = _region_stats_for_features(features)[:8]

    lats, lngs = [], []
    for feature in features:
        if feature.latitude is not None and feature.longitude is not None:
            lats.append(float(feature.latitude))
            lngs.append(float(feature.longitude))

    center = None
    if lats and lngs:
        center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}

    count = len(features)
    mineral = layer.mineral

    ctx = {
        "lat": center["lat"] if center else -6.369,
        "lng": center["lng"] if center else 34.888,
        "zoom": 9,
        "region": top_regions[0]["region"] if top_regions else None,
        "minerals": [
            {
                "slug": mineral.slug,
                "name": localized_name(mineral, locale),
                "name_sw": mineral.name_sw,
                "color": _layer_display_color(layer),
                "count": count,
            }
        ],
        "feature_count": count,
        "labels": [],
        "has_mapped_data": count > 0,
        "search_type": "layer",
        "search_name": localized_name(layer, locale),
        "description": f"Uploaded {layer.layer_type} layer",
        "layer_type": layer.layer_type,
        "top_regions": top_regions,
    }
    return _apply_polygon_coverage_totals(ctx, features, user, locale)


def build_search_ai_context(ctx: dict) -> str:
    kind = ctx.get("search_type")
    total_area = ctx.get("total_area_km2")
    area_line = (
        f"Total mapped polygon coverage area: {total_area:.2f} km²\n" if total_area else ""
    )
    if kind == "mineral":
        regions = ", ".join(_format_region_stat_line(r) for r in ctx.get("top_regions", [])) or "none listed"
        desc = ctx.get("description") or "none"
        return (
            f"User searched for mineral: {ctx['search_name']}\n"
            f"Mineral overview: {desc}\n"
            f"Total mapped zones for this mineral on Terra Meta: {ctx['feature_count']}\n"
            f"{area_line}"
            f"Regions where this mineral appears on the map (ranked by zone count): {regions}\n"
            f"Map center for this mineral: {ctx['lat']:.4f}, {ctx['lng']:.4f}\n"
            f"Important: Answer using ONLY the region list, zone counts, and km² values above. "
            f"When asked which regions have the most coverage, rank and cite the regions listed above. "
            f"Do not say regional data is unavailable if regions are listed.\n"
        )

    if kind == "layer":
        regions = ", ".join(_format_region_stat_line(r) for r in ctx.get("top_regions", [])) or "none listed"
        layer_type = ctx.get("layer_type") or "geometry"
        return (
            f"User searched for uploaded map layer: {ctx['search_name']}\n"
            f"Layer type: {layer_type}\n"
            f"Total mapped features on Terra Meta: {ctx['feature_count']}\n"
            f"{area_line}"
            f"Regions where this layer appears (ranked by zone count): {regions}\n"
            f"Map center: {ctx['lat']:.4f}, {ctx['lng']:.4f}\n"
            f"Important: Summarize using ONLY the mapped counts, regions, and km² values above. "
            f"When asked about top regions, use the ranked region list.\n"
        )

    if kind in ("region_boundary", "district_boundary", "ward_boundary", "village_boundary", "region"):
        commodities = ", ".join(
            f"{m['name']} ({m['count']} zones)" for m in ctx.get("minerals", [])
        ) or "none listed"
        if kind == "district_boundary":
            admin_label = "district"
        elif kind == "ward_boundary":
            admin_label = "ward"
        elif kind == "village_boundary":
            admin_label = "village"
        else:
            admin_label = "region"
        return (
            f"User searched for {admin_label}: {ctx['search_name']}\n"
            f"Total mapped features in this {admin_label}: {ctx['feature_count']}\n"
            f"Commodity layers mapped here: {commodities}\n"
            f"Map center: {ctx['lat']:.4f}, {ctx['lng']:.4f}\n"
            f"Country: Tanzania\n"
            f"Important: Summarize only the commodities and counts listed above.\n"
        )

    return (
        f"User searched for area: {ctx.get('search_name', 'unknown')}\n"
        f"Total mapped features: {ctx.get('feature_count', 0)}\n"
    )


def generate_basic_search_insight(ctx: dict, locale: str = "en") -> str:
    kind = ctx.get("search_type")
    if not ctx.get("has_mapped_data"):
        if kind == "mineral":
            if locale == "sw":
                return f"Hakuna maeneo yaliyopangwa kwa {ctx['search_name']} kwenye ramani."
            return f"No mapped zones for {ctx['search_name']} are available on the map yet."
        if kind == "layer":
            if locale == "sw":
                return f"Hakuna vipengele vilivyopangwa kwa tabaka {ctx['search_name']}."
            return f"No mapped features are available for layer {ctx['search_name']} yet."
        if locale == "sw":
            return f"Hakuna data ya madini iliyopangwa kwa {ctx['search_name']}."
        return f"No mapped mineral zones are available for {ctx['search_name']} yet."

    if kind == "layer":
        regions = ctx.get("top_regions") or []
        layer_type = ctx.get("layer_type") or "layer"
        if locale == "sw":
            lines = [
                f"{ctx['search_name']} ({layer_type}) ina vipengele {ctx['feature_count']} vilivyopangwa.",
            ]
            if regions:
                top = ", ".join(f"{r['region']} ({r['count']})" for r in regions[:4])
                lines.append(f"Mikoa kuu: {top}.")
        else:
            lines = [
                f"{ctx['search_name']} ({layer_type}) has {ctx['feature_count']} mapped features on Terra Meta.",
            ]
            if regions:
                top = ", ".join(_format_region_stat_line(r) for r in regions[:4])
                lines.append(f"Top regions on the map: {top}.")
        total_area = ctx.get("total_area_km2")
        if total_area:
            lines.append(f"Total mapped polygon area: {total_area:.2f} km².")
        return " ".join(lines)

    if kind == "mineral":
        regions = ctx.get("top_regions") or []
        if locale == "sw":
            lines = [
                f"{ctx['search_name']} inaonekana kwenye ramani katika maeneo {ctx['feature_count']}.",
            ]
            if regions:
                top = ", ".join(_format_region_stat_line(r) for r in regions[:4])
                lines.append(f"Mikoa kuu: {top}.")
        else:
            lines = [
                f"{ctx['search_name']} appears across {ctx['feature_count']} mapped zones on Terra Meta.",
            ]
            if regions:
                top = ", ".join(_format_region_stat_line(r) for r in regions[:4])
                lines.append(f"Top regions on the map: {top}.")
        total_area = ctx.get("total_area_km2")
        if total_area:
            if locale == "sw":
                lines.append(f"Jumla ya eneo la poligoni lililopangwa: {total_area:.2f} km².")
            else:
                lines.append(f"Total mapped polygon area: {total_area:.2f} km².")
        desc = (ctx.get("description") or "").strip()
        if desc:
            lines.append(desc)
        return " ".join(lines)

    minerals = ctx.get("minerals") or []
    if locale == "sw":
        mineral_line = ", ".join(f"{m['name']} ({m['count']})" for m in minerals[:5]) or "hakuna"
        return (
            f"{ctx['search_name']} ina maeneo {ctx['feature_count']} yaliyopangwa. "
            f"Madini kwenye ramani: {mineral_line}."
        )
    mineral_line = ", ".join(f"{m['name']} ({m['count']} zones)" for m in minerals[:5]) or "none"
    return (
        f"{ctx['search_name']} has {ctx['feature_count']} mapped zones. "
        f"Minerals on the map: {mineral_line}."
    )


def _feature_region_name(feature: MapFeature, lat: float, lng: float) -> str | None:
    props = feature.properties or {}
    prop_region = props.get("region")
    if prop_region:
        return str(prop_region)
    if feature.layer.region:
        return feature.layer.region.name
    return region_at_point(lat, lng)


def _feature_in_analysis_zone(
    feature: MapFeature,
    lat: float,
    lng: float,
    area_km2: float,
) -> bool:
    from .map_view_area import analysis_zone_radius_km, haversine_km

    radius_km = analysis_zone_radius_km(area_km2)
    lat_delta, lng_delta = analysis_zone_deltas_degrees(lat, area_km2)
    lat_min, lat_max = lat - lat_delta, lat + lat_delta
    lng_min, lng_max = lng - lng_delta, lng + lng_delta

    if feature.latitude is not None and feature.longitude is not None:
        if haversine_km(lat, lng, feature.latitude, feature.longitude) <= radius_km:
            return True

    bbox = geometry_bbox(feature.geometry)
    if bbox:
        min_lat, max_lat, min_lng, max_lng = bbox
        if max_lat < lat_min or min_lat > lat_max or max_lng < lng_min or min_lng > lng_max:
            return False
        closest_lat = min(max(lat, min_lat), max_lat)
        closest_lng = min(max(lng, min_lng), max_lng)
        if haversine_km(lat, lng, closest_lat, closest_lng) <= radius_km:
            return True

    return feature_contains_click(
        lat,
        lng,
        feature.geometry,
        feature.layer.layer_type,
        12,
    )


def _area_insight_candidates(
    lat: float,
    lng: float,
    zoom: int,
    user,
    feature_ids: list[int] | None = None,
    *,
    analysis_area_km2: float | None = None,
):
    base_qs = _accessible_features(user).select_related(
        "layer", "layer__mineral", "layer__region"
    )

    if feature_ids:
        matched: list[MapFeature] = []
        for feature in base_qs.filter(id__in=feature_ids)[:50]:
            if feature_contains_click(
                lat,
                lng,
                feature.geometry,
                feature.layer.layer_type,
                zoom,
            ):
                matched.append(feature)
        if matched:
            return matched

    seen: set[int] = set()
    candidates: list[MapFeature] = []

    zone_km2 = analysis_area_km2 or included_analysis_km2()
    lat_delta, lng_delta = analysis_zone_deltas_degrees(lat, zone_km2)
    lat_min, lat_max = lat - lat_delta, lat + lat_delta
    lng_min, lng_max = lng - lng_delta, lng + lng_delta
    delta = max(lat_delta, lng_delta)

    for feature in base_qs.filter(
        latitude__gte=lat_min,
        latitude__lte=lat_max,
        longitude__gte=lng_min,
        longitude__lte=lng_max,
    )[:500]:
        if feature.id not in seen:
            seen.add(feature.id)
            candidates.append(feature)

    if len(candidates) < 500:
        for feature in base_qs.filter(
            layer__layer_type__in=[
                MapLayer.LayerType.POLYGON,
                MapLayer.LayerType.LINE,
            ]
        ).exclude(id__in=seen)[:1200]:
            bbox = geometry_bbox(feature.geometry)
            if bbox and bbox_intersects_click(bbox, lat, lng, delta):
                seen.add(feature.id)
                candidates.append(feature)
            if len(candidates) >= 500:
                break

    return candidates


def _feature_in_admin_boundary(feature: MapFeature, boundary_geometry: dict) -> bool:
    from apps.maps.geometry_utils import geometry_bbox, point_in_geometry

    if feature.latitude is not None and feature.longitude is not None:
        if point_in_geometry(feature.longitude, feature.latitude, boundary_geometry):
            return True
    bbox = geometry_bbox(feature.geometry)
    if bbox:
        min_lat, max_lat, min_lng, max_lng = bbox
        clat = (min_lat + max_lat) / 2
        clng = (min_lng + max_lng) / 2
        if point_in_geometry(clng, clat, boundary_geometry):
            return True
    if feature.geometry:
        return point_in_geometry(
            feature.longitude or 0,
            feature.latitude or 0,
            boundary_geometry,
        )
    return False


def area_location_context(
    lat: float,
    lng: float,
    zoom: int,
    user,
    locale: str = "en",
    feature_ids: list[int] | None = None,
    *,
    analysis_area_km2: float | None = None,
    admin_boundary_id: int | None = None,
    country_code: str = "TZ",
) -> dict:
    from apps.geography.admin_boundary_service import lookup_boundaries_at_point
    from apps.geography.models import AdminBoundary, Country

    zone_km2 = analysis_area_km2 or included_analysis_km2()
    insight_scope = "analysis_zone"

    admin_boundary = None
    if admin_boundary_id:
        admin_boundary = AdminBoundary.objects.filter(id=admin_boundary_id).first()

    matched: list[MapFeature] = []

    if feature_ids:
        for feature in _accessible_features(user).select_related("layer", "layer__mineral", "layer__region").filter(
            id__in=feature_ids
        )[:50]:
            if feature_contains_click(
                lat,
                lng,
                feature.geometry,
                feature.layer.layer_type,
                zoom,
            ):
                matched.append(feature)

    if not matched and admin_boundary:
        matched = features_in_boundary(admin_boundary, _accessible_feature_list(user, limit=5000))
        insight_scope = "admin_boundary"
    elif not matched:
        candidates = _area_insight_candidates(
            lat,
            lng,
            zoom,
            user,
            feature_ids,
            analysis_area_km2=zone_km2,
        )
        for feature in candidates:
            if not _feature_in_analysis_zone(feature, lat, lng, zone_km2):
                continue
            if admin_boundary and not _feature_in_admin_boundary(feature, admin_boundary.geometry):
                continue
            matched.append(feature)

    admin_lookup = {"region": None, "district": None, "ward": None, "village": None}
    try:
        country = Country.objects.get(code=country_code.upper())
        admin_lookup = lookup_boundaries_at_point(country, lat, lng)
    except Country.DoesNotExist:
        pass

    labels = []
    for feature in matched:
        if feature.label:
            labels.append(feature.label)

    minerals_list = commodities_from_features(
        matched,
        locale=locale,
        include_polygon_area=user_has_map_detail_access(user),
    )

    region_counts: dict[str, int] = defaultdict(int)
    for feature in matched:
        region_name = _feature_region_name(feature, lat, lng)
        if region_name:
            region_counts[region_name] += 1

    top_region = (
        max(region_counts.items(), key=lambda x: x[1])[0]
        if region_counts
        else (admin_lookup.get("region") or {}).get("name") or region_at_point(lat, lng, country_code)
    )

    district_info = admin_lookup.get("district")
    region_info = admin_lookup.get("region")
    ward_info = admin_lookup.get("ward")
    village_info = admin_lookup.get("village")

    return {
        "lat": lat,
        "lng": lng,
        "zoom": zoom,
        "region": top_region,
        "geographic_region": (region_info or {}).get("name") or region_at_point(lat, lng, country_code),
        "region_boundary": region_info,
        "district_boundary": district_info,
        "ward_boundary": ward_info,
        "village_boundary": village_info,
        "minerals": minerals_list,
        "feature_count": len(matched),
        "labels": labels[:8],
        "has_mapped_data": len(matched) > 0,
        "analysis_area_km2": zone_km2,
        "insight_scope": insight_scope,
    }


def _commodity_summary_line(commodity: dict) -> str:
    line = f"{commodity['name']} ({commodity['count']} zones"
    area = commodity.get("area_km2")
    if area:
        line += f", {area:.2f} km² polygon area"
    return f"{line})"


def _admin_hierarchy_lines(ctx: dict, *, locale: str = "en") -> str:
    region = (ctx.get("region_boundary") or {}).get("name")
    district = (ctx.get("district_boundary") or {}).get("name")
    ward = (ctx.get("ward_boundary") or {}).get("name")
    village = (ctx.get("village_boundary") or {}).get("name")
    lines: list[str] = []
    if locale == "sw":
        if region:
            lines.append(f"Mkoa: {region}")
        if district:
            lines.append(f"Wilaya: {district}")
        if ward:
            lines.append(f"Kata: {ward}")
        if village:
            lines.append(f"Kijiji: {village}")
    else:
        if region:
            lines.append(f"Region: {region}")
        if district:
            lines.append(f"District: {district}")
        if ward:
            lines.append(f"Ward: {ward}")
        if village:
            lines.append(f"Village: {village}")
    return "\n".join(lines)


def build_area_ai_context(ctx: dict) -> str:
    zone = ctx.get("analysis_area_km2") or included_analysis_km2()
    mineral_lines = ", ".join(
        _commodity_summary_line(m) for m in ctx.get("minerals", [])
    ) or "No mapped zones in this analysis area"
    labels = ", ".join(ctx.get("labels", [])[:5]) or "none"
    region = ctx.get("region") or "not assigned"
    geo = ctx.get("geographic_region") or region
    admin_lines = _admin_hierarchy_lines(ctx)
    if ctx.get("insight_scope") == "admin_boundary":
        boundary = (
            ctx.get("village_boundary")
            or ctx.get("ward_boundary")
            or ctx.get("district_boundary")
            or ctx.get("region_boundary")
            or {}
        )
        boundary_name = boundary.get("name") or geo
        scope_line = f"Mapped zones within administrative boundary: {boundary_name}\n"
    else:
        scope_line = (
            f"Analysis zone: {zone:.1f} km² square centered on {ctx['lat']:.4f}, {ctx['lng']:.4f} "
            f"(zoom {ctx['zoom']})\n"
        )
    admin_block = f"{admin_lines}\n" if admin_lines else ""
    return (
        f"{scope_line}"
        f"{admin_block}"
        f"Administrative region at click: {geo}\n"
        f"Mapped zone region (from feature data): {region}\n"
        f"Minerals in this analysis zone (mapped data only): {mineral_lines}\n"
        f"Mapped zone count in zone: {ctx['feature_count']}\n"
        f"Zone labels: {labels}\n"
        f"Country: Tanzania\n"
        f"Important: Only describe the location and minerals listed above. Do not infer geology for other areas.\n"
    )


def generate_unmapped_insight(lat: float, lng: float, locale: str = "en") -> str:
    if locale == "sw":
        return (
            f"Hakuna data ya uhakika ya uchambuzi wa madini kwa eneo hili ({lat:.3f}, {lng:.3f}).\n"
            "Bofya ndani ya poligoni au alama iliyopangwa kwenye ramani, "
            "au tafuta mkoa unaoripotiwa kwenye tabaka zilizochapishwa."
        )
    return (
        f"No proven mineral mapping or reports are available for this exact location "
        f"({lat:.3f}, {lng:.3f}).\n"
        "Click inside a mapped polygon, on a mapped line, or on a mapped point, "
        "or explore a region with published layers."
    )


def generate_basic_map_insight(ctx: dict, locale: str = "en") -> str:
    """Template-based insight from proven mapped features at the click point only."""
    if not ctx.get("has_mapped_data"):
        return generate_unmapped_insight(ctx["lat"], ctx["lng"], locale)

    minerals = ctx.get("minerals", [])
    region = ctx.get("region") or ("Haijulikani" if locale == "sw" else "Unassigned")
    admin_lines = _admin_hierarchy_lines(ctx, locale=locale)

    if locale == "sw":
        lines = []
        if admin_lines:
            lines.append(admin_lines)
        lines.extend([
            f"Mkoa (kutoka data iliyopangwa): {region}",
            (
                f"Maeneo {ctx.get('feature_count', 0)} yaliyopangwa katika eneo hili"
                if ctx.get("insight_scope") == "admin_boundary"
                else f"Maeneo {ctx.get('feature_count', 0)} yaliyopangwa mahali ulipobofya"
            ),
        ])
    else:
        lines = []
        if admin_lines:
            lines.append(admin_lines)
        lines.extend([
            f"Mapped region: {region}",
            (
                f"{ctx.get('feature_count', 0)} mapped zone(s) in this area"
                if ctx.get("insight_scope") == "admin_boundary"
                else f"{ctx.get('feature_count', 0)} mapped zone(s) at your click point"
            ),
        ])
    for m in minerals[:4]:
        line = f"• {m['name']}: {m['count']} zone(s)"
        if m.get("area_km2"):
            if locale == "sw":
                line += f", {m['area_km2']:.2f} km² jumla ya poligoni"
            else:
                line += f", {m['area_km2']:.2f} km² total polygon area"
        lines.append(line)
    labels = ctx.get("labels") or []
    if labels:
        if locale == "sw":
            lines.append(f"Maeneo: {', '.join(labels[:3])}")
        else:
            lines.append(f"Zones include: {', '.join(labels[:3])}")
    return "\n".join(lines)


def build_platform_ai_context(locale: str = "en") -> str:
    """Compact background facts for unpaid users (not a script to recite)."""
    minerals = Mineral.objects.filter(is_active=True).order_by("name")[:8]
    names = ", ".join(localized_name(m, locale) for m in minerals)
    if locale == "sw":
        return (
            f"Jukwaa: Terra Meta, jukwaa la ujasili wa madini.\n"
            f"Madini kwenye ramani: {names or 'mbalimbali'}.\n"
            "Bure: kuchunguza ramani, kujifunza kuhusu jukwaa hapa.\n"
            "Usajili: lebo za maeneo, uchambuzi, maarifa ya eneo kutoka AI, ripoti."
        )
    return (
        f"Product: Terra Meta, a mineral intelligence platform.\n"
        f"Map minerals include: {names or 'several commodities'}.\n"
        "Free tier: browse the map and ask about the platform here.\n"
        "Paid: zone labels, analytics, location AI on map clicks, report downloads."
    )
