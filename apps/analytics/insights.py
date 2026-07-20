"""Location and mineral insight helpers for map search and area queries."""

from collections import defaultdict

import math

from django.db.models import Q

from apps.geography.models import AdminBoundary, Country, Region
from apps.geography.region_geo import region_at_point, region_center, region_zoom
from apps.maps.access import filter_layers_for_user, layers_with_mapped_data, user_has_map_detail_access
from apps.maps.geometry_utils import (
    bbox_intersects_click,
    distance_geometry_to_point_km,
    feature_contains_click,
    geometry_area_km2,
    geometry_bbox,
    geometry_line_trend_degrees,
    undirected_trend_degrees,
)
from apps.maps.localization import localized_name
from apps.maps.models import MapFeature, MapLayer
from apps.maps.structure_props import extract_orientation_degrees
from apps.minerals.models import Mineral

from .map_view_area import analysis_zone_deltas_degrees, included_analysis_km2
from .spatial_assign import (
    AdminBoundaryIndex,
    boundary_center_and_bounds,
    commodities_from_features,
    feature_sample_point,
    features_in_boundary,
    features_in_exploration_scope,
    is_line_feature,
    is_point_feature,
    is_polygon_feature,
)


def parse_exploration_geometry(raw) -> dict | None:
    """Parse GeoJSON geometry from API query/body (dict or JSON string)."""
    import json

    if not raw:
        return None
    if isinstance(raw, dict):
        return raw if raw.get("type") and raw.get("coordinates") is not None else None
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and data.get("type") and data.get("coordinates") is not None:
            return data
    return None


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
        return f"{row['region']} ({row['count']} areas, {area:.2f} km²)"
    return f"{row['region']} ({row['count']} areas)"


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


def catalog_mineral_coverage_context(
    catalog_slug: str,
    user,
    locale: str = "en",
    *,
    country_code: str = "TZ",
) -> dict | None:
    """Aggregate map layers, features, and reports for a periodic-table commodity."""
    from apps.reports.models import Report

    from .mineral_coverage import _feature_counts_by_layer, layers_for_catalog_slug

    layers = layers_for_catalog_slug(catalog_slug, country_code=country_code)
    if not layers:
        return mineral_coverage_context(catalog_slug, user, locale=locale)

    layer_ids = {layer.id for layer in layers}
    layer_counts = _feature_counts_by_layer(layer_ids)
    features: list[MapFeature] = []
    for layer in layers:
        batch = list(
            _accessible_features(user)
            .filter(layer=layer)
            .select_related("layer", "layer__region", "layer__mineral")[:1200]
        )
        features.extend(batch)
        if len(features) >= 1200:
            features = features[:1200]
            break

    top_regions = _region_stats_for_features(features)[:8]
    lats, lngs = [], []
    for feature in features:
        if feature.latitude and feature.longitude:
            lats.append(float(feature.latitude))
            lngs.append(float(feature.longitude))

    center = None
    if lats and lngs:
        center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}

    mineral_slugs = {layer.mineral.slug for layer in layers if layer.mineral_id}
    mineral = None
    try:
        mineral = Mineral.objects.get(slug=catalog_slug, is_active=True)
    except Mineral.DoesNotExist:
        mineral = None

    search_name = localized_name(mineral, locale) if mineral else localized_name(layers[0], locale)
    description = (mineral.description if mineral else layers[0].description) or ""

    connected_layers = [
        {
            "id": layer.id,
            "slug": layer.slug,
            "name": localized_name(layer, locale),
            "layer_type": layer.layer_type,
            "feature_count": layer_counts.get(layer.id, 0),
        }
        for layer in layers
    ]

    reports_qs = (
        Report.objects.filter(is_active=True)
        .select_related("mineral", "region")
        .filter(
            Q(mineral__slug=catalog_slug)
            | Q(mineral__slug__in=mineral_slugs)
            | Q(layers__id__in=layer_ids)
        )
        .distinct()[:12]
    )
    related_reports = [
        {
            "slug": report.slug,
            "title": report.title,
            "access_type": report.access_type,
            "has_article": report.has_article,
            "region": localized_name(report.region, locale) if report.region else None,
        }
        for report in reports_qs
    ]

    ctx = {
        "lat": center["lat"] if center else -6.369,
        "lng": center["lng"] if center else 34.888,
        "zoom": 9,
        "region": top_regions[0]["region"] if top_regions else None,
        "minerals": [
            {
                "slug": catalog_slug,
                "name": search_name,
                "name_sw": mineral.name_sw if mineral else (layers[0].name_sw or ""),
                "color": mineral.color if mineral else _layer_display_color(layers[0]),
                "count": len(features),
            }
        ],
        "feature_count": len(features),
        "labels": [],
        "has_mapped_data": len(features) > 0,
        "search_type": "mineral",
        "search_name": search_name,
        "description": description,
        "top_regions": top_regions,
        "connected_layers": connected_layers,
        "related_reports": related_reports,
        "catalog_slug": catalog_slug,
    }
    return _apply_polygon_coverage_totals(ctx, features, user, locale)


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

    from apps.geography.geology_context import geology_context_for_boundary

    ctx = {
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
    geology = geology_context_for_boundary(boundary, locale)
    if geology.get("entries"):
        ctx["geological_context"] = geology
    return ctx


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
    description = (layer.description or "").strip() or f"Uploaded {layer.layer_type} layer"
    attribute_samples = _feature_attribute_samples(features, max_features=10)

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
        "labels": [f.label for f in features if f.label][:8],
        "has_mapped_data": count > 0,
        "search_type": "layer",
        "search_name": localized_name(layer, locale),
        "description": description,
        "layer_type": layer.layer_type,
        "top_regions": top_regions,
        "feature_attributes": attribute_samples,
    }
    return _apply_polygon_coverage_totals(ctx, features, user, locale)


def build_search_ai_context(ctx: dict) -> str:
    kind = ctx.get("search_type")
    total_area = ctx.get("total_area_km2")
    area_line = (
        f"Total mapped mineral coverage area: {total_area:.2f} km²\n" if total_area else ""
    )
    if kind == "mineral":
        regions = ", ".join(_format_region_stat_line(r) for r in ctx.get("top_regions", [])) or "none listed"
        desc = ctx.get("description") or "none"
        layer_lines = ", ".join(
            f"{row['name']} ({row['layer_type']}, {row['feature_count']} features)"
            for row in ctx.get("connected_layers", [])
        ) or "none listed"
        report_lines = ", ".join(row["title"] for row in ctx.get("related_reports", [])) or "none listed"
        return (
            f"User searched for mineral: {ctx['search_name']}\n"
            f"Mineral overview: {desc}\n"
            f"Total mapped areas for this mineral on Terra Meta: {ctx['feature_count']}\n"
            f"{area_line}"
            f"Connected map layers (polygons, points, structures): {layer_lines}\n"
            f"Related Terra reports and studies: {report_lines}\n"
            f"Regions where this mineral appears on the map (ranked by area count): {regions}\n"
            f"Map center for this mineral: {ctx['lat']:.4f}, {ctx['lng']:.4f}\n"
            f"Important: Answer using ONLY the layer list, report list, region list, area counts, and km² values above. "
            f"When asked which regions have the most coverage, rank and cite the regions listed above. "
            f"Reference connected reports when relevant. Do not say regional data is unavailable if regions are listed.\n"
        )

    if kind == "layer":
        regions = ", ".join(_format_region_stat_line(r) for r in ctx.get("top_regions", [])) or "none listed"
        layer_type = ctx.get("layer_type") or "geometry"
        desc = ctx.get("description") or "none"
        attribute_block = _format_feature_attribute_block(ctx.get("feature_attributes") or [])
        return (
            f"User searched for uploaded map layer: {ctx['search_name']}\n"
            f"Layer type: {layer_type}\n"
            f"Layer description: {desc}\n"
            f"Total mapped features on Terra Meta: {ctx['feature_count']}\n"
            f"{area_line}"
            f"Regions where this layer appears (ranked by area count): {regions}\n"
            f"Map center: {ctx['lat']:.4f}, {ctx['lng']:.4f}\n"
            f"{attribute_block}"
            f"Important: Summarize using ONLY the mapped counts, regions, km² values, "
            f"layer description, and feature attributes above. "
            f"When asked about top regions, use the ranked region list.\n"
        )

    if kind in ("region_boundary", "district_boundary", "ward_boundary", "village_boundary", "region"):
        commodities = ", ".join(
            f"{m['name']} ({m['count']} areas)" for m in ctx.get("minerals", [])
        ) or "none listed"
        if kind == "district_boundary":
            admin_label = "district"
        elif kind == "ward_boundary":
            admin_label = "ward"
        elif kind == "village_boundary":
            admin_label = "village"
        else:
            admin_label = "region"
        geology = ctx.get("geological_context") or {}
        geology_block = f"{geology['ai_block']}\n" if geology.get("ai_block") else ""
        return (
            f"User searched for {admin_label}: {ctx['search_name']}\n"
            f"Total mapped features in this {admin_label}: {ctx['feature_count']}\n"
            f"Commodity layers mapped here: {commodities}\n"
            f"Map center: {ctx['lat']:.4f}, {ctx['lng']:.4f}\n"
            f"Country: Tanzania\n"
            f"{geology_block}"
            f"Important: Summarize commodities, counts, and geological reference above. "
            f"Use geological context when explaining area setting and mineral potential.\n"
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
            return f"No mapped areas for {ctx['search_name']} are available on the map yet."
        if kind == "layer":
            if locale == "sw":
                return f"Hakuna vipengele vilivyopangwa kwa tabaka {ctx['search_name']}."
            return f"No mapped features are available for layer {ctx['search_name']} yet."
        if locale == "sw":
            return f"Hakuna data ya madini iliyopangwa kwa {ctx['search_name']}."
        return f"No mapped mineral areas are available for {ctx['search_name']} yet."

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
            lines.append(f"Total mapped mineral area: {total_area:.2f} km².")
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
                f"{ctx['search_name']} appears across {ctx['feature_count']} mapped areas on Terra Meta.",
            ]
            if regions:
                top = ", ".join(_format_region_stat_line(r) for r in regions[:4])
                lines.append(f"Top regions on the map: {top}.")
        total_area = ctx.get("total_area_km2")
        if total_area:
            if locale == "sw":
                lines.append(f"Jumla ya eneo la madini lililopangwa: {total_area:.2f} km².")
            else:
                lines.append(f"Total mapped mineral area: {total_area:.2f} km².")
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
    mineral_line = ", ".join(f"{m['name']} ({m['count']} areas)" for m in minerals[:5]) or "none"
    return (
        f"{ctx['search_name']} has {ctx['feature_count']} mapped areas. "
        f"Minerals on the map: {mineral_line}."
    )


_COMPASS_SECTOR_RANGES: tuple[tuple[str, float, float], ...] = (
    ("N", 337.5, 22.5),
    ("NE", 22.5, 67.5),
    ("E", 67.5, 112.5),
    ("SE", 112.5, 157.5),
    ("S", 157.5, 202.5),
    ("SW", 202.5, 247.5),
    ("W", 247.5, 292.5),
    ("NW", 292.5, 337.5),
)

_COMPASS_SECTOR_ORDER = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _bearing_degrees(center_lat: float, center_lng: float, point_lat: float, point_lng: float) -> float:
    phi1 = math.radians(center_lat)
    phi2 = math.radians(point_lat)
    d_lambda = math.radians(point_lng - center_lng)
    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _bearing_to_sector(bearing: float) -> str:
    for label, start, end in _COMPASS_SECTOR_RANGES:
        if start > end:
            if bearing >= start or bearing < end:
                return label
        elif start <= bearing < end:
            return label
    return "N"


def _sector_label_full(sector: str, locale: str = "en") -> str:
    labels_en = {
        "N": "north",
        "NE": "northeast",
        "E": "east",
        "SE": "southeast",
        "S": "south",
        "SW": "southwest",
        "W": "west",
        "NW": "northwest",
    }
    labels_sw = {
        "N": "kaskazini",
        "NE": "kaskazini-mashariki",
        "E": "mashariki",
        "SE": "kusini-mashariki",
        "S": "kusini",
        "SW": "kusini-magharibi",
        "W": "magharibi",
        "NW": "kaskazini-magharibi",
    }
    table = labels_sw if locale == "sw" else labels_en
    return table.get(sector, sector.lower())


def _direction_distribution_parts(sectors: dict[str, int], locale: str = "en") -> list[str]:
    parts: list[str] = []
    for sector in _COMPASS_SECTOR_ORDER:
        count = int(sectors.get(sector, 0) or 0)
        if count:
            parts.append(f"{count} {_sector_label_full(sector, locale)}")
    return parts


def _direction_summary_lines(
    overall: dict[str, int],
    by_mineral: list[dict],
    *,
    locale: str = "en",
) -> list[str]:
    lines: list[str] = []
    total = sum(int(v or 0) for v in overall.values())
    if total < 1:
        return lines

    parts = _direction_distribution_parts(overall, locale)
    if parts:
        if locale == "sw":
            lines.append(
                f"Maeneo {total} yaliyopangwa kulingana na kituo cha uchambuzi: {', '.join(parts)}."
            )
        else:
            zone_word = "areas" if total != 1 else "area"
            lines.append(
                f"{total} mapped {zone_word} relative to the analysis center: {', '.join(parts)}."
            )

    for entry in by_mineral[:4]:
        dominant_count = int(entry.get("dominant_count") or 0)
        mineral_total = int(entry.get("count") or 0)
        if mineral_total < 1 or dominant_count < 1:
            continue
        share = dominant_count / mineral_total
        if mineral_total >= 2 and share < 0.5:
            continue
        name = entry.get("name") or entry.get("slug") or "Mineral"
        direction = entry.get("dominant_direction") or _sector_label_full(
            str(entry.get("dominant_sector") or "N"), locale
        )
        if locale == "sw":
            lines.append(
                f"**{name}** linazingatia upande wa {direction} "
                f"({dominant_count} kati ya {mineral_total} maeneo)."
            )
        else:
            lines.append(
                f"**{name}** areas cluster toward the {direction} "
                f"({dominant_count} of {mineral_total} areas)."
            )

    return lines


def direction_insights_for_features(
    features: list[MapFeature],
    center_lat: float,
    center_lng: float,
    minerals_list: list[dict],
    *,
    locale: str = "en",
) -> dict | None:
    """Compass-sector distribution of mapped areas relative to the analysis center."""
    if not features:
        return None

    overall: dict[str, int] = defaultdict(int)
    by_slug: dict[str, dict] = {}

    for feature in features:
        point_lat, point_lng = feature_sample_point(feature)
        if not point_lat and not point_lng:
            continue
        sector = _bearing_to_sector(_bearing_degrees(center_lat, center_lng, point_lat, point_lng))
        overall[sector] += 1
        mineral = feature.layer.mineral if feature.layer else None
        slug = mineral.slug if mineral else "unknown"
        name = localized_name(mineral, locale) if mineral else "Unknown"
        if slug not in by_slug:
            by_slug[slug] = {"name": name, "sectors": defaultdict(int)}
        by_slug[slug]["sectors"][sector] += 1

    if not overall:
        return None

    by_mineral: list[dict] = []
    mineral_order = {m.get("slug"): idx for idx, m in enumerate(minerals_list)}
    for slug, payload in sorted(
        by_slug.items(),
        key=lambda item: (mineral_order.get(item[0], 999), -sum(item[1]["sectors"].values())),
    ):
        sectors = {key: int(value) for key, value in payload["sectors"].items()}
        total = sum(sectors.values())
        if total < 1:
            continue
        dominant_sector, dominant_count = max(sectors.items(), key=lambda item: item[1])
        mineral_meta = next((m for m in minerals_list if m.get("slug") == slug), {})
        by_mineral.append(
            {
                "slug": slug,
                "name": mineral_meta.get("name") or payload["name"],
                "count": total,
                "sectors": sectors,
                "dominant_sector": dominant_sector,
                "dominant_direction": _sector_label_full(dominant_sector, locale),
                "dominant_count": dominant_count,
            }
        )

    summary_lines = _direction_summary_lines(overall, by_mineral, locale=locale)
    return {
        "center": {"lat": center_lat, "lng": center_lng},
        "sectors": dict(overall),
        "by_mineral": by_mineral,
        "summary_lines": summary_lines,
    }


_STRUCTURE_TREND_RANGES = (
    ("N-S", 0.0, 22.5, 157.5, 180.0),
    ("NE-SW", 22.5, 67.5, None, None),
    ("E-W", 67.5, 112.5, None, None),
    ("NW-SE", 112.5, 157.5, None, None),
)

_STRUCTURE_TREND_ORDER = ("N-S", "NE-SW", "E-W", "NW-SE")

_PRIORITY_ORIENTATION_KEYS = frozenset(
    {
        "trend_deg",
        "strike_0_180",
        "strike_deg",
        "strike",
        "trend",
        "azimuth",
        "azimuth_deg",
        "bearing",
        "bearing_deg",
        "structure_type",
        "structure_rank",
        "structurerank",
    }
)


def _undirected_trend_bin(trend_0_180: float) -> str:
    t = float(trend_0_180) % 180.0
    for label, start, end, start2, end2 in _STRUCTURE_TREND_RANGES:
        if start2 is not None and end2 is not None:
            if start <= t < end or start2 <= t < end2:
                return label
        elif start <= t < end:
            return label
    return "N-S"


def _trend_bin_label(bin_key: str, locale: str = "en") -> str:
    if locale == "sw":
        labels = {
            "N-S": "K–S",
            "NE-SW": "KM–SM",
            "E-W": "M–M",
            "NW-SE": "KM–SK",
        }
        return labels.get(bin_key, bin_key)
    return bin_key.replace("-", "–")


def _feature_orientation_degrees(feature: MapFeature) -> tuple[float, str] | None:
    """
    Return (undirected 0–180 trend, source) from attributes or line geometry.
    Attribute values win over geometry-derived bearings.
    """
    props = feature.properties if isinstance(feature.properties, dict) else {}
    from_props = extract_orientation_degrees(props)
    if from_props is not None:
        return undirected_trend_degrees(from_props), "property"

    if is_line_feature(feature):
        from_geom = geometry_line_trend_degrees(
            feature.geometry if isinstance(feature.geometry, dict) else None
        )
        if from_geom is not None:
            return from_geom, "geometry"
    return None


def _structure_orientation_summary_lines(
    overall: dict[str, int],
    by_mineral: list[dict],
    *,
    dominant_trend: str | None,
    mean_trend_deg: float | None,
    count_with_orientation: int,
    property_count: int,
    geometry_count: int,
    locale: str = "en",
) -> list[str]:
    lines: list[str] = []
    if count_with_orientation < 1 or not dominant_trend:
        return lines

    trend_label = _trend_bin_label(dominant_trend, locale)
    dominant_count = int(overall.get(dominant_trend, 0) or 0)
    mean_bit = ""
    if mean_trend_deg is not None:
        mean_bit = (
            f" (wastani wa mwelekeo {mean_trend_deg:.0f}°)"
            if locale == "sw"
            else f" (mean trend {mean_trend_deg:.0f}°)"
        )

    if locale == "sw":
        lines.append(
            f"Miundo {count_with_orientation} yenye mwelekeo: "
            f"mtindo mkuu **{trend_label}** ({dominant_count} kati ya {count_with_orientation})"
            f"{mean_bit}."
        )
        source_bits = []
        if property_count:
            source_bits.append(f"{property_count} kutoka sifa")
        if geometry_count:
            source_bits.append(f"{geometry_count} kutoka jiometri ya miundo")
        if source_bits:
            lines.append(f"Chanzo: {', '.join(source_bits)}.")
    else:
        lines.append(
            f"{count_with_orientation} mapped structure"
            f"{'s' if count_with_orientation != 1 else ''} with orientation: "
            f"dominant trend **{trend_label}** ({dominant_count} of {count_with_orientation})"
            f"{mean_bit}."
        )
        source_bits = []
        if property_count:
            source_bits.append(f"{property_count} from attributes")
        if geometry_count:
            source_bits.append(f"{geometry_count} from structure geometry")
        if source_bits:
            lines.append(f"Source: {', '.join(source_bits)}.")

    for entry in by_mineral[:3]:
        if int(entry.get("count") or 0) < 2:
            continue
        name = entry.get("name") or entry.get("slug") or "Layer"
        d_label = _trend_bin_label(str(entry.get("dominant_trend") or ""), locale)
        if locale == "sw":
            lines.append(
                f"**{name}**: mtindo mkuu {d_label} "
                f"({entry.get('dominant_count')} kati ya {entry.get('count')})."
            )
        else:
            lines.append(
                f"**{name}**: dominant {d_label} "
                f"({entry.get('dominant_count')} of {entry.get('count')})."
            )
    return lines


def structure_orientation_insights_for_features(
    features: list[MapFeature],
    minerals_list: list[dict],
    *,
    locale: str = "en",
) -> dict | None:
    """
    Geological fabric trends (strike/trend), distinct from compass clustering vs center.
    Prefers property strike/trend/azimuth; falls back to line-geometry bearings.
    """
    if not features:
        return None

    overall: dict[str, int] = defaultdict(int)
    by_slug: dict[str, dict] = {}
    trends: list[float] = []
    property_count = 0
    geometry_count = 0

    for feature in features:
        oriented = _feature_orientation_degrees(feature)
        if oriented is None:
            # Include bare line features in line_count stats only via commodities;
            # skip orientation when neither attribute nor computable geometry exists.
            continue
        trend, source = oriented
        bin_key = _undirected_trend_bin(trend)
        overall[bin_key] += 1
        trends.append(trend)
        if source == "property":
            property_count += 1
        else:
            geometry_count += 1

        mineral = feature.layer.mineral if feature.layer else None
        slug = mineral.slug if mineral else (feature.layer.slug if feature.layer else "unknown")
        name = localized_name(mineral, locale) if mineral else (
            localized_name(feature.layer, locale) if feature.layer else "Unknown"
        )
        if slug not in by_slug:
            by_slug[slug] = {"name": name, "bins": defaultdict(int)}
        by_slug[slug]["bins"][bin_key] += 1

    if not overall:
        return None

    # Circular mean of undirected trends (double-angle).
    sum_sin = sum(math.sin(math.radians(t * 2.0)) for t in trends)
    sum_cos = sum(math.cos(math.radians(t * 2.0)) for t in trends)
    mean_trend_deg = None
    if abs(sum_sin) > 1e-15 or abs(sum_cos) > 1e-15:
        mean_trend_deg = round(
            undirected_trend_degrees(math.degrees(0.5 * math.atan2(sum_sin, sum_cos))),
            1,
        )

    dominant_trend, _ = max(overall.items(), key=lambda item: item[1])

    by_mineral: list[dict] = []
    mineral_order = {m.get("slug"): idx for idx, m in enumerate(minerals_list)}
    for slug, payload in sorted(
        by_slug.items(),
        key=lambda item: (mineral_order.get(item[0], 999), -sum(item[1]["bins"].values())),
    ):
        bins = {key: int(value) for key, value in payload["bins"].items()}
        total = sum(bins.values())
        if total < 1:
            continue
        d_bin, d_count = max(bins.items(), key=lambda item: item[1])
        mineral_meta = next((m for m in minerals_list if m.get("slug") == slug), {})
        by_mineral.append(
            {
                "slug": slug,
                "name": mineral_meta.get("name") or payload["name"],
                "count": total,
                "bins": bins,
                "dominant_trend": d_bin,
                "dominant_trend_label": _trend_bin_label(d_bin, locale),
                "dominant_count": d_count,
            }
        )

    count_with_orientation = sum(overall.values())
    summary_lines = _structure_orientation_summary_lines(
        overall,
        by_mineral,
        dominant_trend=dominant_trend,
        mean_trend_deg=mean_trend_deg,
        count_with_orientation=count_with_orientation,
        property_count=property_count,
        geometry_count=geometry_count,
        locale=locale,
    )

    return {
        "dominant_trend": dominant_trend,
        "dominant_trend_label": _trend_bin_label(dominant_trend, locale),
        "mean_trend_deg": mean_trend_deg,
        "count_with_orientation": count_with_orientation,
        "property_count": property_count,
        "geometry_count": geometry_count,
        "bins": dict(overall),
        "by_mineral": by_mineral,
        "summary_lines": summary_lines,
    }


def _feature_region_name(feature: MapFeature, lat: float, lng: float) -> str | None:
    props = feature.properties or {}
    prop_region = props.get("region")
    if prop_region:
        return str(prop_region)
    if feature.layer.region:
        return feature.layer.region.name
    return region_at_point(lat, lng)


_SKIP_PROPERTY_KEYS = {
    "geometry",
    "geom",
    "shape",
    "the_geom",
    "wkb_geometry",
    "shape_leng",
    "shape_area",
    "objectid",
    "fid",
    "gid",
}


def _serialize_feature_properties(props: dict | None, *, max_keys: int = 12) -> dict[str, str]:
    if not isinstance(props, dict) or not props:
        return {}

    def _storable_item(key: str, value) -> tuple[str, str] | None:
        key_l = str(key).strip().lower()
        if not key_l or key_l in _SKIP_PROPERTY_KEYS:
            return None
        if value is None or value == "":
            return None
        if isinstance(value, (dict, list)):
            return None
        text = str(value).strip()
        if not text or len(text) > 160:
            return None
        return str(key), text

    prioritized: list[tuple[str, str]] = []
    rest: list[tuple[str, str]] = []
    for key, value in props.items():
        item = _storable_item(key, value)
        if not item:
            continue
        key_l = str(key).strip().lower().replace(" ", "_")
        if key_l in _PRIORITY_ORIENTATION_KEYS or key_l.replace("_", "") in {
            k.replace("_", "") for k in _PRIORITY_ORIENTATION_KEYS
        }:
            prioritized.append(item)
        else:
            rest.append(item)

    out: dict[str, str] = {}
    for key, text in prioritized + rest:
        if len(out) >= max_keys:
            break
        out[key] = text
    return out


def _feature_attribute_samples(
    features: list[MapFeature],
    *,
    max_features: int = 8,
) -> list[dict]:
    samples: list[dict] = []
    for feature in features[:max_features]:
        props = _serialize_feature_properties(feature.properties or {})
        layer = feature.layer
        sample = {
            "feature_id": feature.id,
            "label": feature.label or "",
            "layer_id": layer.id if layer else None,
            "layer_name": layer.name if layer else "",
            "layer_type": layer.layer_type if layer else "",
            "layer_description": (layer.description or "").strip() if layer else "",
            "properties": props,
        }
        if sample["label"] or sample["properties"] or sample["layer_description"]:
            samples.append(sample)
    return samples


def _format_feature_attribute_block(samples: list[dict]) -> str:
    if not samples:
        return ""
    lines = ["Layer feature attributes (from uploaded map data):"]
    for sample in samples:
        header_bits = [
            bit
            for bit in (
                sample.get("layer_name"),
                sample.get("layer_type"),
                sample.get("label"),
            )
            if bit
        ]
        header = " · ".join(header_bits) or f"feature {sample.get('feature_id')}"
        lines.append(f"- {header}")
        desc = (sample.get("layer_description") or "").strip()
        if desc:
            lines.append(f"  layer description: {desc[:200]}")
        props = sample.get("properties") or {}
        for key, value in list(props.items())[:10]:
            lines.append(f"  {key}: {value}")
    lines.append(
        "Use these attribute fields when answering questions about grades, host rock, "
        "licenses, names, or other uploaded layer properties."
    )
    return "\n".join(lines) + "\n"


def _layer_influence_radius_km(layer: MapLayer, zone_km2: float) -> float:
    """Per-layer influence radius: configured buffer or default analysis area."""
    from .map_view_area import analysis_zone_radius_km

    if layer.buffer_km:
        return float(layer.buffer_km)
    return analysis_zone_radius_km(zone_km2)


def _feature_distance_to_point_km(feature: MapFeature, lat: float, lng: float) -> float:
    if feature.geometry:
        distance = distance_geometry_to_point_km(lat, lng, feature.geometry)
        if math.isfinite(distance):
            return distance
    if feature.latitude is not None and feature.longitude is not None:
        from .map_view_area import haversine_km

        return haversine_km(lat, lng, feature.latitude, feature.longitude)
    return float("inf")


def _feature_in_analysis_zone(
    feature: MapFeature,
    lat: float,
    lng: float,
    area_km2: float,
) -> bool:
    from .map_view_area import haversine_km

    radius_km = _layer_influence_radius_km(feature.layer, area_km2)
    if _feature_distance_to_point_km(feature, lat, lng) <= radius_km:
        return True

    lat_delta, lng_delta = analysis_zone_deltas_degrees(lat, area_km2)
    lat_min, lat_max = lat - lat_delta, lat + lat_delta
    lng_min, lng_max = lng - lng_delta, lng + lng_delta

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


def _max_influence_radius_km(user, zone_km2: float) -> float:
    from .map_view_area import analysis_zone_radius_km

    base = analysis_zone_radius_km(zone_km2)
    buffered = (
        _accessible_layers(user)
        .exclude(buffer_km__isnull=True)
        .order_by("-buffer_km")
        .values_list("buffer_km", flat=True)
        .first()
    )
    if buffered:
        return max(base, float(buffered))
    return base


def _expand_matches_with_reference_buffers(
    anchors: list[MapFeature],
    matched: list[MapFeature],
    user,
) -> tuple[list[MapFeature], list[dict]]:
    """Include influencing features within each anchor layer's reference buffer."""
    seen = {feature.id for feature in matched}
    references: list[dict] = []
    buffered_anchors = [anchor for anchor in anchors if anchor.layer.buffer_km]
    if not buffered_anchors:
        return matched, references

    all_features = _accessible_feature_list(user, limit=5000)
    for anchor in buffered_anchors:
        buffer_km = float(anchor.layer.buffer_km)
        alat, alng = feature_sample_point(anchor)
        references.append(
            {
                "layer_name": anchor.layer.name,
                "buffer_km": int(buffer_km),
                "anchor_label": anchor.label or f"Feature {anchor.id}",
                "lat": alat,
                "lng": alng,
            }
        )
        for feature in all_features:
            if feature.id in seen:
                continue
            if _feature_distance_to_point_km(feature, alat, alng) <= buffer_km:
                seen.add(feature.id)
                matched.append(feature)

    return matched, references


def features_in_analysis_zone(
    user,
    lat: float,
    lng: float,
    zoom: int = 12,
    *,
    feature_ids: list[int] | None = None,
    analysis_area_km2: float | None = None,
) -> list[MapFeature]:
    """Mapped features that fall inside the analysis area for exports and snapshots."""
    zone_km2 = analysis_area_km2 or included_analysis_km2()
    candidates = _area_insight_candidates(
        lat,
        lng,
        zoom,
        user,
        feature_ids,
        analysis_area_km2=zone_km2,
    )
    return [feature for feature in candidates if _feature_in_analysis_zone(feature, lat, lng, zone_km2)]


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
    max_radius_km = _max_influence_radius_km(user, zone_km2)
    lat_delta = max_radius_km / 111.0
    lng_delta = max_radius_km / max(111.0 * abs(math.cos(math.radians(lat))), 1e-6)
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
    exploration_geometry: dict | None = None,
    country_code: str = "TZ",
    visible_layer_ids: list[int] | None = None,
) -> dict:
    from apps.geography.admin_boundary_service import lookup_boundaries_at_point
    from apps.geography.models import AdminBoundary, Country

    zone_km2 = analysis_area_km2 or included_analysis_km2()
    insight_scope = "analysis_zone"

    admin_boundary = None
    if admin_boundary_id:
        admin_boundary = AdminBoundary.objects.filter(id=admin_boundary_id).first()

    matched: list[MapFeature] = []
    anchor_features: list[MapFeature] = []
    reference_buffers: list[dict] = []
    scoped_to_exploration = False

    if exploration_geometry:
        exploration_matched = features_in_exploration_scope(
            _accessible_feature_list(user, limit=5000),
            exploration_geometry,
        )
        if exploration_matched:
            matched = exploration_matched
            insight_scope = "exploration_area"
            scoped_to_exploration = True

    if feature_ids and not scoped_to_exploration:
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
                anchor_features.append(feature)

    if matched and anchor_features and not scoped_to_exploration:
        matched, reference_buffers = _expand_matches_with_reference_buffers(
            anchor_features,
            matched,
            user,
        )
        if reference_buffers:
            insight_scope = "reference_buffer"

    if not matched and admin_boundary:
        boundary_matched = features_in_boundary(
            admin_boundary, _accessible_feature_list(user, limit=5000)
        )
        if boundary_matched:
            matched = boundary_matched
            insight_scope = "admin_boundary"

    if not matched:
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
            matched.append(feature)

    if visible_layer_ids:
        allowed = set(visible_layer_ids)
        matched = [feature for feature in matched if feature.layer_id in allowed]
        anchor_features = [feature for feature in anchor_features if feature.layer_id in allowed]

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
        # Clip to the circular search zone only for map-click analysis.
        # Admin / exploration scopes already constrain features; use full extents there.
        area_clip_lat=lat if insight_scope == "analysis_zone" else None,
        area_clip_lng=lng if insight_scope == "analysis_zone" else None,
        area_clip_km2=zone_km2 if insight_scope == "analysis_zone" else None,
    )
    total_area_km2 = sum(float(item.get("area_km2") or 0) for item in minerals_list)
    # Overlapping licences can each contribute up to the zone size; headline total
    # should not exceed the analysis circle for map-click insights.
    if insight_scope == "analysis_zone" and total_area_km2 > 0 and zone_km2:
        total_area_km2 = min(total_area_km2, float(zone_km2))


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
    top_regions = [
        {"region": name, "count": count}
        for name, count in sorted(region_counts.items(), key=lambda x: x[1], reverse=True)[:8]
    ]

    district_info = admin_lookup.get("district")
    region_info = admin_lookup.get("region")
    ward_info = admin_lookup.get("ward")
    village_info = admin_lookup.get("village")

    direction_insights = direction_insights_for_features(
        matched,
        lat,
        lng,
        minerals_list,
        locale=locale,
    )
    structure_orientations = structure_orientation_insights_for_features(
        matched,
        minerals_list,
        locale=locale,
    )

    result = {
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
        "occurrence_count": sum(1 for feature in matched if is_point_feature(feature)),
        "polygon_count": sum(1 for feature in matched if is_polygon_feature(feature)),
        "line_count": sum(1 for feature in matched if is_line_feature(feature)),
        "labels": labels[:8],
        "has_mapped_data": len(matched) > 0,
        "analysis_area_km2": zone_km2,
        "total_area_km2": round(total_area_km2, 2) if total_area_km2 > 0 else None,
        "insight_scope": insight_scope,
        "reference_buffers": reference_buffers,
        "top_regions": top_regions,
        "exploration_geometry": exploration_geometry,
        "direction_insights": direction_insights,
        "structure_orientations": structure_orientations,
        "feature_attributes": _feature_attribute_samples(matched),
        "layer_notes": [
            {
                "layer_id": layer.id,
                "name": localized_name(layer, locale),
                "layer_type": layer.layer_type,
                "description": (layer.description or "").strip(),
            }
            for layer in {
                feature.layer_id: feature.layer for feature in matched if feature.layer_id
            }.values()
            if (layer.description or "").strip()
        ],
    }
    result["country_code"] = country_code
    from apps.geography.geology_context import attach_geological_context

    attach_geological_context(
        result,
        locale=locale,
        boundary_id=admin_boundary_id if insight_scope == "admin_boundary" else None,
    )
    return result


def enrich_area_insight_context(
    ctx: dict,
    *,
    basemap: str | None = None,
    locale: str = "en",
) -> dict:
    """Attach basemap framing and DEM terrain metrics to an area insight context."""
    from .basemap_metadata import basemap_ai_block, basemap_label, normalize_basemap
    from .terrain_context import build_terrain_context

    bid = normalize_basemap(basemap)
    if bid:
        ctx["basemap"] = bid
        ctx["basemap_label"] = basemap_label(bid, locale=locale)
        ctx["basemap_insight_hint"] = basemap_ai_block(bid, locale=locale)

    terrain = build_terrain_context(
        float(ctx["lat"]),
        float(ctx["lng"]),
        analysis_area_km2=ctx.get("analysis_area_km2"),
        locale=locale,
    )
    if terrain:
        ctx["terrain_context"] = terrain

    return ctx


def _commodity_summary_line(commodity: dict) -> str:
    occurrences = int(commodity.get("occurrence_count") or 0)
    polygons = int(commodity.get("polygon_count") or 0)
    lines = int(commodity.get("line_count") or 0)
    parts: list[str] = []
    if occurrences:
        parts.append(
            f"{occurrences} occurrence{'s' if occurrences != 1 else ''} (points)"
        )
    if polygons:
        parts.append(f"{polygons} polygon area{'s' if polygons != 1 else ''}")
    if lines:
        parts.append(f"{lines} structure{'s' if lines != 1 else ''}")
    if not parts:
        total = int(commodity.get("count") or 0)
        parts.append(f"{total} mapped feature{'s' if total != 1 else ''}")
    line = f"{commodity['name']} ({', '.join(parts)}"
    area = commodity.get("area_km2")
    if area:
        line += f", {area:.2f} km² within analysis area"
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
    ) or "No mapped areas in this analysis area"
    labels = ", ".join(ctx.get("labels", [])[:5]) or "none"
    region = ctx.get("region") or "not assigned"
    geo = ctx.get("geographic_region") or region
    admin_lines = _admin_hierarchy_lines(ctx)
    total_inside = ctx.get("total_area_km2")
    area_inside_line = (
        f"Total mineral polygon coverage inside the analysis area: {float(total_inside):.2f} km² "
        f"(intersection with the search circle, not full licence extents)\n"
        if total_inside
        else ""
    )
    if ctx.get("insight_scope") == "admin_boundary":
        boundary = (
            ctx.get("village_boundary")
            or ctx.get("ward_boundary")
            or ctx.get("district_boundary")
            or ctx.get("region_boundary")
            or {}
        )
        boundary_name = boundary.get("name") or geo
        scope_line = f"Mapped areas within administrative boundary: {boundary_name}\n"
    elif ctx.get("insight_scope") == "reference_buffer":
        refs = ctx.get("reference_buffers") or []
        ref_lines = "\n".join(
            (
                f"Reference buffer: {ref['layer_name']} — {ref['buffer_km']} km around "
                f"{ref['anchor_label']} ({ref['lat']:.4f}, {ref['lng']:.4f})"
            )
            for ref in refs
        )
        scope_line = (
            f"Analysis anchored on mapped feature(s); influencing factors within reference buffer(s):\n"
            f"{ref_lines}\n"
        )
    elif ctx.get("insight_scope") == "exploration_area":
        scope_line = (
            "Analysis limited to the user's drawn exploration area on the map. "
            "Do not describe minerals or areas outside this geometry.\n"
        )
    else:
        scope_line = (
            f"Analysis area: {zone:.1f} km² square centered on {ctx['lat']:.4f}, {ctx['lng']:.4f} "
            f"(zoom {ctx['zoom']})\n"
        )
    admin_block = f"{admin_lines}\n" if admin_lines else ""
    direction = ctx.get("direction_insights") or {}
    direction_block = ""
    if direction.get("sectors"):
        sector_bits = ", ".join(
            f"{sector}={direction['sectors'].get(sector, 0)}"
            for sector in _COMPASS_SECTOR_ORDER
            if direction["sectors"].get(sector, 0)
        )
        direction_block = f"Compass distribution from analysis center (sector counts): {sector_bits}\n"
        for entry in direction.get("by_mineral") or []:
            direction_block += (
                f"- {entry.get('name')}: dominant {entry.get('dominant_direction')} "
                f"({entry.get('dominant_count')} of {entry.get('count')} areas)\n"
            )
        for line in direction.get("summary_lines") or []:
            direction_block += f"- {line}\n"
        direction_block += (
            "Describe spatial clustering using these compass directions when relevant. "
            "This is where mapped features lie relative to the analysis center — "
            "not geological strike/trend of structures.\n"
        )
    structure = ctx.get("structure_orientations") or {}
    structure_block = ""
    if structure.get("count_with_orientation"):
        structure_block = (
            "Mapped structure orientations (geological trend/strike fabric, "
            "NOT compass clustering from the analysis center):\n"
            f"- overall dominant trend: {structure.get('dominant_trend_label')} "
            f"({structure.get('count_with_orientation')} oriented features"
        )
        if structure.get("mean_trend_deg") is not None:
            structure_block += f"; mean trend {structure['mean_trend_deg']:.0f}°"
        structure_block += ")\n"
        bin_bits = ", ".join(
            f"{_trend_bin_label(bin_key)}={structure['bins'].get(bin_key, 0)}"
            for bin_key in _STRUCTURE_TREND_ORDER
            if structure.get("bins", {}).get(bin_key)
        )
        if bin_bits:
            structure_block += f"- trend bins: {bin_bits}\n"
        if structure.get("property_count") or structure.get("geometry_count"):
            structure_block += (
                f"- sources: {int(structure.get('property_count') or 0)} attribute, "
                f"{int(structure.get('geometry_count') or 0)} structure geometry\n"
            )
        for entry in structure.get("by_mineral") or []:
            structure_block += (
                f"- {entry.get('name')}: dominant {entry.get('dominant_trend_label')} "
                f"({entry.get('dominant_count')} of {entry.get('count')})\n"
            )
        for line in structure.get("summary_lines") or []:
            structure_block += f"- {line}\n"
        structure_block += (
            "Use these only as mapped structural fabric. Do not invent fold axes, "
            "fault kinematics, or dip directions beyond the provided data.\n"
        )
    geology_block = ""
    geology = ctx.get("geological_context") or {}
    if geology.get("ai_block"):
        geology_block = f"{geology['ai_block']}\n"
    private_geo_block = ""
    try:
        from apps.geography.geo_reference import build_private_geo_reference_ai_block
        from .map_view_area import analysis_zone_radius_km

        zone = ctx.get("analysis_area_km2") or included_analysis_km2()
        # Search a bit wider than the analysis circle so nearby reference polygons can help.
        radius_km = max(analysis_zone_radius_km(zone) * 3.0, 15.0)
        lat = ctx.get("lat")
        lng = ctx.get("lng")
        if lat is not None and lng is not None:
            private_geo_block = build_private_geo_reference_ai_block(
                float(lat),
                float(lng),
                radius_km=radius_km,
            )
    except Exception:
        private_geo_block = ""
    basemap_block = ""
    if ctx.get("basemap_insight_hint"):
        basemap_block = f"{ctx['basemap_insight_hint']}\n"
    terrain_block = ""
    terrain = ctx.get("terrain_context") or {}
    if terrain.get("ai_block"):
        terrain_block = f"{terrain['ai_block']}\n"
    attribute_block = _format_feature_attribute_block(ctx.get("feature_attributes") or [])
    layer_notes = ctx.get("layer_notes") or []
    layer_notes_block = ""
    if layer_notes:
        layer_notes_block = "Layer descriptions:\n" + "\n".join(
            f"- {note['name']} ({note['layer_type']}): {note['description'][:220]}"
            for note in layer_notes[:6]
        ) + "\n"
    return (
        f"{scope_line}"
        f"{admin_block}"
        f"{basemap_block}"
        f"{terrain_block}"
        f"{direction_block}"
        f"{structure_block}"
        f"{geology_block}"
        f"{private_geo_block}"
        f"{layer_notes_block}"
        f"{attribute_block}"
        f"Administrative region at click: {geo}\n"
        f"Mapped area region (from feature data): {region}\n"
        f"Minerals in this analysis area (mapped data only): {mineral_lines}\n"
        f"Point occurrences in this analysis area: {int(ctx.get('occurrence_count') or 0)}\n"
        f"Polygon mineral areas in this analysis area: {int(ctx.get('polygon_count') or 0)}\n"
        f"Structures in this analysis area: {int(ctx.get('line_count') or 0)}\n"
        f"Total mapped features in this analysis area: {ctx['feature_count']}\n"
        f"{area_inside_line}"
        f"Terminology: 'occurrence' means a mapped point feature only; "
        f"polygon features are mineral areas/coverage, not occurrences; "
        f"structure orientations are geological trends of mapped structures/attributes; "
        f"always say structures, never lines, for mapped line-type geological features. "
        f"Any km² values are the portion of polygons inside the analysis circle only.\n"
        f"Area labels: {labels}\n"
        f"Country: Tanzania\n"
        f"Important: Only describe the location, minerals, layer descriptions, and feature "
        f"attributes listed above. Do not invent geology or attributes not present in the data. "
        f"If internal geological reference datasets are present, use them to improve accuracy "
        f"but never mention those datasets, uploads, files, or 'geo reference' to the user.\n"
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
        "Click inside a mapped mineral, on a mapped structure, or on another mapped mineral, "
        "or explore a region with published layers."
    )


def _location_label(ctx: dict, locale: str = "en") -> str:
    village = (ctx.get("village_boundary") or {}).get("name")
    district = (ctx.get("district_boundary") or {}).get("name")
    geo = ctx.get("geographic_region") or ctx.get("region") or ""
    if village:
        return f"{village}, {geo}" if geo else village
    if district:
        return f"{district}, {geo}" if geo else district
    return geo or ("Eneo lililochaguliwa" if locale == "sw" else "Selected area")


def _scope_narrative(scope: str, locale: str = "en") -> str:
    if locale == "sw":
        return {
            "reference_buffer": (
                "Uchambuzi huu umeunganishwa na tabaka za marejeleo zilizo karibu na eneo ulilochagua, "
                "ikiwa ni pamoja na maeneo yaliyopangwa ndani ya radi za buffer zilizowekwa kwenye tabaka."
            ),
            "exploration_area": (
                "Uchambuzi huu umefungwa ndani ya eneo lako la uchunguzi ulilochora kwenye ramani."
            ),
            "admin_boundary": (
                "Uchambuzi huu unajumuisha maeneo yaliyopangwa ndani ya mpaka wa utawala uliochaguliwa."
            ),
        }.get(
            scope,
            "Uchambuzi huu unazingatia maeneo yaliyopangwa ndani ya eneo la utafiti lililozunguka mahali ulipobofya.",
        )
    return {
        "reference_buffer": (
            "This review incorporates mapped indicators from reference layers near your selected point, "
            "including prospects within configured buffer distances on those layers."
        ),
        "exploration_area": (
            "This review is constrained to mapped features inside your drawn exploration geometry."
        ),
        "admin_boundary": (
            "This review aggregates mapped prospects within the selected administrative boundary."
        ),
    }.get(
        scope,
        "This review considers mapped mineral prospects within the circular analysis area around your selected point.",
    )


def _mineral_exploration_notes(slug: str, name: str, locale: str = "en") -> str:
    token = f"{slug} {name}".lower()
    notes_en = {
        "zinc": (
            "Zinc targets on regional maps typically justify structural-lithological mapping, "
            "soil and rock-chip geochemistry, and IP or resistivity grids to trace sulphide "
            "halos before trenching or scout drilling."
        ),
        "uranium": (
            "Uranium indicators call for radiometric surveying, detailed alteration mapping, "
            "and early engagement on environmental and licensing requirements before any ground disturbance."
        ),
        "gold": (
            "Gold prospects merit regolith-aware soil sampling, stream sediment follow-up, "
            "and structural interpretation of the mapped footprint before RAB or RC drilling."
        ),
        "copper": (
            "Copper occurrences often respond to induced polarization and magnetics; combine "
            "geophysics with petrographic work on any outcrop or artisanal workings in the mineral area."
        ),
        "nickel": (
            "Nickel targets may relate to ultramafic or lateritic settings; auger or pit sampling "
            "for Ni and associated pathfinders should precede deeper drilling."
        ),
        "iron": (
            "Iron mapping mineral areas support magnetic surveying and pitting to confirm grade continuity "
            "and stripping ratios for potential DSO or magnetite projects."
        ),
        "coal": (
            "Coal indicators require stratigraphic section measurement, core or trench confirmation, "
            "and assessment of basin continuity and infrastructure access."
        ),
        "graphite": (
            "Graphite prospects benefit from mapping of graphitic schists or gneisses, grab sampling "
            "for carbon grade, and metallurgical scoping early in the program."
        ),
        "lithium": (
            "Lithium targets may be pegmatite-hosted or brine-related; field work should confirm "
            "mineral assemblages and use appropriate geochem paths (Li, Cs, Ta, Rb) before drilling."
        ),
    }
    notes_sw = {
        "zinc": (
            "Malengo ya zinki huahidi uchambuzi wa kimuundo, jeochemistry ya udongo na miamba, "
            "na gridi za IP/resistivity kabla ya trenching au uchunguzi wa mashimo."
        ),
        "uranium": (
            "Viashiria vya urani vinahitaji uchunguzi wa radiometriki, uainishaji wa mabadiliko "
            "ya mwamba, na uthibitishaji wa leseni na mazingira mapema."
        ),
        "gold": (
            "Malengo ya dhahabu vinahitaji sampuli za udongo, sediment za mito, na tafsiri ya "
            "kimuundo kabla ya kuchimba mashimo ya uchunguzi."
        ),
    }
    catalog = notes_sw if locale == "sw" else notes_en
    for key, note in catalog.items():
        if key in token:
            return note
    if locale == "sw":
        return (
            f"Kwa {name}, panga ramani ya shamba, sampuli za jeochemistry, gridi za geophysiki "
            f"inazofaa kwa bidhaa hiyo, na uthibitishaji wa leseni kabla ya uamuzi wa kuchimba."
        )
    return (
        f"For {name}, plan reconnaissance mapping, commodity-appropriate geochemical sampling, "
        f"targeted geophysical grids, and tenure verification before committing to drill holes."
    )


def _insight_contradicts_mapped_data(text: str, ctx: dict) -> bool:
    if not ctx.get("has_mapped_data") or not ctx.get("minerals"):
        return False
    lower = (text or "").lower()
    bad_phrases = (
        "no mapped areas",
        "no mapped area",
        "no proven mineral",
        "no minerals",
        "nothing mapped",
    )
    return any(phrase in lower for phrase in bad_phrases)


def generate_basic_map_insight(ctx: dict, locale: str = "en") -> str:
    """Structured map-click report from mapped features in the analysis scope."""
    from .map_report_format import build_map_report_markdown

    return build_map_report_markdown(ctx, locale=locale)


def build_platform_ai_context(locale: str = "en") -> str:
    """Compact background facts for unpaid users (not a script to recite)."""
    minerals = Mineral.objects.filter(is_active=True).order_by("name")[:8]
    names = ", ".join(localized_name(m, locale) for m in minerals)
    if locale == "sw":
        return (
            f"Jukwaa: Terra Meta, jukwaa la ujasili wa madini.\n"
            f"Madini kwenye ramani: {names or 'mbalimbali'}.\n"
            "Bure: kuchunguza ramani, kujifunza kuhusu jukwaa hapa.\n"
            "Usajili: lebo za maeneo, uchambuzi, maarifa ya eneo kutoka Terra, ripoti."
        )
    return (
        f"Product: Terra Meta, a mineral intelligence platform.\n"
        f"Map minerals include: {names or 'several commodities'}.\n"
        "Free tier: browse the map and ask about the platform here.\n"
        "Paid: area labels, analytics, location Terra insights on map clicks, report downloads."
    )
