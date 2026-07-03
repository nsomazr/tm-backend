"""Location and mineral insight helpers for map search and area queries."""

from collections import defaultdict

from django.db.models import Q

from apps.geography.models import Region
from apps.geography.region_geo import region_at_point, region_center, region_zoom
from apps.maps.access import filter_layers_for_user, user_has_map_detail_access
from apps.maps.geometry_utils import (
    bbox_intersects_click,
    feature_contains_click,
    geometry_bbox,
)
from apps.maps.localization import localized_name
from apps.maps.models import MapFeature, MapLayer
from apps.minerals.models import Mineral


def _accessible_layers(user):
    qs = MapLayer.objects.filter(is_active=True).select_related("mineral", "region")
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


def mineral_search_insights(query: str, user, limit: int = 8) -> list[dict]:
    q = query.strip()
    if not q:
        return []

    layer_ids = set(_accessible_layers(user).values_list("id", flat=True))
    results = []
    seen_names: set[str] = set()

    regions = (
        Region.objects.filter(is_active=True)
        .filter(Q(name__icontains=q) | Q(name_sw__icontains=q))
        .select_related("country")[:limit]
    )
    for region in regions:
        center = _region_center(region, layer_ids)
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
                "total_layer_count": MapLayer.objects.filter(region=region, is_active=True).count(),
                "top_regions": [],
                "top_minerals": top_minerals,
                "center": center,
                "zoom": region_zoom(region.name) if center else 10,
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

        region_counts: dict[str, int] = defaultdict(int)
        lats, lngs = [], []
        for feature in features[:500]:
            if feature.layer.region:
                region_counts[feature.layer.region.name] += 1
            if feature.latitude and feature.longitude:
                lats.append(float(feature.latitude))
                lngs.append(float(feature.longitude))

        top_regions = sorted(
            [{"region": k, "count": v} for k, v in region_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        center = None
        if lats and lngs:
            center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}

        total_layers = MapLayer.objects.filter(mineral=mineral, is_active=True).count()
        accessible_layer_count = MapLayer.objects.filter(
            mineral=mineral, is_active=True, id__in=layer_ids
        ).count()

        results.append(
            {
                "type": "mineral",
                "id": mineral.id,
                "name": mineral.name,
                "name_sw": mineral.name_sw,
                "slug": mineral.slug,
                "color": mineral.color,
                "description": mineral.description,
                "feature_count": features.count(),
                "layer_count": accessible_layer_count,
                "total_layer_count": total_layers,
                "top_regions": top_regions,
                "top_minerals": [],
                "center": center,
                "zoom": 9,
                "has_full_data": user_has_map_detail_access(user),
            }
        )

    return results[:limit]


def mineral_coverage_context(mineral_slug: str, user, locale: str = "en") -> dict | None:
    try:
        mineral = Mineral.objects.get(slug=mineral_slug, is_active=True)
    except Mineral.DoesNotExist:
        return None

    features = list(
        _accessible_features(user, mineral_slug=mineral_slug).select_related("layer__region")[:1200]
    )
    region_counts: dict[str, int] = defaultdict(int)
    lats, lngs = [], []
    for feature in features:
        if feature.layer.region:
            region_counts[feature.layer.region.name] += 1
        if feature.latitude and feature.longitude:
            lats.append(float(feature.latitude))
            lngs.append(float(feature.longitude))

    top_regions = sorted(
        [{"region": k, "count": v} for k, v in region_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    center = None
    if lats and lngs:
        center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}

    top_region = top_regions[0]["region"] if top_regions else None
    count = len(features)

    return {
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


def build_search_ai_context(ctx: dict) -> str:
    kind = ctx.get("search_type")
    if kind == "mineral":
        regions = ", ".join(
            f"{r['region']} ({r['count']} zones)" for r in ctx.get("top_regions", [])
        ) or "none listed"
        desc = ctx.get("description") or "none"
        return (
            f"User searched for mineral: {ctx['search_name']}\n"
            f"Mineral overview: {desc}\n"
            f"Total mapped zones for this mineral on Terra Meta: {ctx['feature_count']}\n"
            f"Regions where this mineral appears on the map (from mapped layers): {regions}\n"
            f"Map center for this mineral: {ctx['lat']:.4f}, {ctx['lng']:.4f}\n"
            f"Country: Tanzania\n"
            f"Important: Describe where explorers can find this mineral based ONLY on the mapped "
            f"regions and zone counts above. Do not invent locations not in the data.\n"
        )

    minerals = ", ".join(
        f"{m['name']} ({m['count']} zones)" for m in ctx.get("minerals", [])
    ) or "none listed"
    return (
        f"User searched for region: {ctx['search_name']}\n"
        f"Total mapped mineral zones in this region: {ctx['feature_count']}\n"
        f"Minerals mapped in this region (from published layers): {minerals}\n"
        f"Map center for this region: {ctx['lat']:.4f}, {ctx['lng']:.4f}\n"
        f"Country: Tanzania\n"
        f"Important: Summarize which minerals are available in this region based ONLY on the "
        f"mapped data above. Do not infer geology outside listed minerals and counts.\n"
    )


def generate_basic_search_insight(ctx: dict, locale: str = "en") -> str:
    kind = ctx.get("search_type")
    if not ctx.get("has_mapped_data"):
        if kind == "mineral":
            if locale == "sw":
                return f"Hakuna maeneo yaliyopangwa kwa {ctx['search_name']} kwenye ramani."
            return f"No mapped zones for {ctx['search_name']} are available on the map yet."
        if locale == "sw":
            return f"Hakuna data ya madini iliyopangwa kwa {ctx['search_name']}."
        return f"No mapped mineral zones are available for {ctx['search_name']} yet."

    if kind == "mineral":
        regions = ctx.get("top_regions") or []
        if locale == "sw":
            lines = [
                f"{ctx['search_name']} inaonekana kwenye ramani katika maeneo {ctx['feature_count']}.",
            ]
            if regions:
                top = ", ".join(f"{r['region']} ({r['count']})" for r in regions[:4])
                lines.append(f"Mikoa kuu: {top}.")
        else:
            lines = [
                f"{ctx['search_name']} appears across {ctx['feature_count']} mapped zones on Terra Meta.",
            ]
            if regions:
                top = ", ".join(f"{r['region']} ({r['count']} zones)" for r in regions[:4])
                lines.append(f"Top regions on the map: {top}.")
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


def _area_insight_candidates(
    lat: float,
    lng: float,
    zoom: int,
    user,
    feature_ids: list[int] | None = None,
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

    delta = _prefilter_delta(zoom)
    lat_min, lat_max = lat - delta, lat + delta
    lng_min, lng_max = lng - delta, lng + delta

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


def area_location_context(
    lat: float,
    lng: float,
    zoom: int,
    user,
    locale: str = "en",
    feature_ids: list[int] | None = None,
) -> dict:
    candidates = _area_insight_candidates(lat, lng, zoom, user, feature_ids)

    matched = []
    for feature in candidates:
        if feature_contains_click(
            lat,
            lng,
            feature.geometry,
            feature.layer.layer_type,
            zoom,
        ):
            matched.append(feature)

    minerals_map: dict[str, dict] = {}
    labels = []

    for feature in matched:
        mineral = feature.layer.mineral
        if mineral.slug not in minerals_map:
            minerals_map[mineral.slug] = {
                "slug": mineral.slug,
                "name": localized_name(mineral, locale),
                "name_sw": mineral.name_sw,
                "color": mineral.color,
                "count": 0,
            }
        minerals_map[mineral.slug]["count"] += 1
        if feature.label:
            labels.append(feature.label)

    minerals_list = sorted(minerals_map.values(), key=lambda m: m["count"], reverse=True)

    region_counts: dict[str, int] = defaultdict(int)
    for feature in matched:
        region_name = _feature_region_name(feature, lat, lng)
        if region_name:
            region_counts[region_name] += 1

    top_region = (
        max(region_counts.items(), key=lambda x: x[1])[0]
        if region_counts
        else region_at_point(lat, lng)
    )

    return {
        "lat": lat,
        "lng": lng,
        "zoom": zoom,
        "region": top_region,
        "geographic_region": region_at_point(lat, lng),
        "minerals": minerals_list,
        "feature_count": len(matched),
        "labels": labels[:8],
        "has_mapped_data": len(matched) > 0,
    }


def build_area_ai_context(ctx: dict) -> str:
    mineral_lines = ", ".join(
        f"{m['name']} ({m['count']} zones)" for m in ctx.get("minerals", [])
    ) or "No mapped zones at this click point"
    labels = ", ".join(ctx.get("labels", [])[:5]) or "none"
    region = ctx.get("region") or "not assigned"
    geo = ctx.get("geographic_region") or region
    return (
        f"Exact click location: {ctx['lat']:.4f}, {ctx['lng']:.4f} (zoom {ctx['zoom']})\n"
        f"Administrative region at click: {geo}\n"
        f"Mapped zone region (from feature data): {region}\n"
        f"Minerals at this exact point (proven mapped data only): {mineral_lines}\n"
        f"Mapped zone count at click: {ctx['feature_count']}\n"
        f"Zone labels at click: {labels}\n"
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

    if locale == "sw":
        lines = [
            f"Mkoa (kutoka data iliyopangwa): {region}",
            f"Maeneo {ctx.get('feature_count', 0)} yaliyopangwa mahali ulipobofya",
        ]
    else:
        lines = [
            f"Mapped region: {region}",
            f"{ctx.get('feature_count', 0)} mapped zone(s) at your click point",
        ]
    for m in minerals[:4]:
        lines.append(f"• {m['name']}: {m['count']} zone(s)")
    labels = ctx.get("labels") or []
    if labels:
        if locale == "sw":
            lines.append(f"Maeneo: {', '.join(labels[:3])}")
        else:
            lines.append(f"Zones include: {', '.join(labels[:3])}")
    return "\n".join(lines)
