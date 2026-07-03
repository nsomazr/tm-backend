"""Location and mineral insight helpers for map search and area queries."""

from collections import defaultdict

from django.db.models import Q

from apps.geography.models import Region
from apps.maps.access import filter_layers_for_user, user_has_map_detail_access
from apps.maps.geometry_utils import feature_contains_click
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
    return None


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
        feature_count = MapFeature.objects.filter(
            is_active=True,
            layer__region=region,
            layer_id__in=layer_ids,
        ).count()
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
                "center": center,
                "zoom": 10,
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
                "center": center,
                "zoom": 9,
                "has_full_data": user_has_map_detail_access(user),
            }
        )

    return results[:limit]


def area_location_context(lat: float, lng: float, zoom: int, user, locale: str = "en") -> dict:
    delta = _prefilter_delta(zoom)
    lat_min, lat_max = lat - delta, lat + delta
    lng_min, lng_max = lng - delta, lng + delta

    candidates = (
        _accessible_features(user)
        .filter(
            latitude__gte=lat_min,
            latitude__lte=lat_max,
            longitude__gte=lng_min,
            longitude__lte=lng_max,
        )
        .exclude(layer__layer_type=MapLayer.LayerType.LINE)
        .select_related("layer", "layer__mineral", "layer__region")[:500]
    )

    matched = []
    for feature in candidates:
        if feature_contains_click(
            lat,
            lng,
            feature.geometry,
            feature.layer.layer_type,
        ):
            matched.append(feature)

    minerals_map: dict[str, dict] = {}
    regions: dict[str, int] = defaultdict(int)
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
        if feature.layer.region:
            regions[feature.layer.region.name] += 1
        if feature.label:
            labels.append(feature.label)

    minerals_list = sorted(minerals_map.values(), key=lambda m: m["count"], reverse=True)
    top_region = (
        max(regions.items(), key=lambda x: x[1])[0] if regions else None
    )

    return {
        "lat": lat,
        "lng": lng,
        "zoom": zoom,
        "region": top_region,
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
    return (
        f"Exact click location: {ctx['lat']:.4f}, {ctx['lng']:.4f} (zoom {ctx['zoom']})\n"
        f"Mapped region label: {region}\n"
        f"Minerals at this exact point (proven mapped data only): {mineral_lines}\n"
        f"Mapped zone count at click: {ctx['feature_count']}\n"
        f"Zone labels at click: {labels}\n"
        f"Country: Tanzania\n"
        f"Important: Only describe what is listed above. Do not infer geology for other areas.\n"
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
        "Click inside a mapped polygon or point on the map, "
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
