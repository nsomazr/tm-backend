"""Mineral catalog and admin-boundary coverage for map highlights."""

from __future__ import annotations

from apps.geography.admin_boundary_service import lookup_boundaries_at_point
from apps.geography.models import AdminBoundary, Country
from apps.maps.access import layers_with_mapped_data
from apps.maps.geometry_utils import geometry_bbox
from apps.maps.localization import localized_name
from apps.maps.models import MapFeature, MapLayer
from apps.minerals.models import Mineral

from .insights import _accessible_features
from .periodic_resolver import resolve_periodic_special, resolve_periodic_z
from .spatial_assign import feature_sample_point, layer_display_color

# Periodic-table slugs → uploaded layer slug(s) on the platform.
PERIODIC_LAYER_SLUGS: dict[str, list[str]] = {
    "lithium": ["lithium"],
    "graphite": ["graphite"],
    "iron-ore": ["iron-ore", "iron"],
    "nickel": ["nickel"],
    "copper": ["copper"],
    "gold": ["gold"],
    "tanzanite": ["tanzanite"],
    "diamond": ["diamond"],
}


def _find_layer_for_catalog_slug(slug: str, layers: list[MapLayer]) -> MapLayer | None:
    by_slug = {layer.slug: layer for layer in layers}
    for candidate in PERIODIC_LAYER_SLUGS.get(slug, [slug]):
        layer = by_slug.get(candidate)
        if layer:
            return layer
    return None


def _feature_counts_by_layer(layer_ids: set[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    if not layer_ids:
        return counts
    for layer_id in (
        MapFeature.objects.filter(is_active=True, layer_id__in=layer_ids)
        .values_list("layer_id", flat=True)
    ):
        counts[layer_id] = counts.get(layer_id, 0) + 1
    return counts


def _layer_catalog_entry(
    layer: MapLayer,
    *,
    slug: str,
    feature_count: int,
    locale: str,
) -> dict:
    return {
        "id": layer.id,
        "slug": slug,
        "name": localized_name(layer, locale),
        "name_sw": layer.name_sw or "",
        "color": layer_display_color(layer),
        "description": layer.description or "",
        "feature_count": feature_count,
        "is_mapped": feature_count > 0,
        "layer_slug": layer.slug,
    }


def mineral_feature_count(mineral_slug: str, user) -> int:
    return _accessible_features(user, mineral_slug=mineral_slug).count()


def _attach_periodic_fields(entry: dict) -> dict:
    slug = entry.get("slug", "")
    entry["periodic_z"] = resolve_periodic_z(slug)
    entry["periodic_special"] = resolve_periodic_special(slug)
    return entry


def build_mineral_catalog(*, country_code: str = "TZ", user=None, locale: str = "en") -> list[dict]:
    user = user if user and getattr(user, "is_authenticated", False) else None
    country = Country.objects.filter(code=country_code.upper()).first()
    if not country:
        return []

    layers = list(
        MapLayer.objects.filter(is_active=True, mineral__country=country).select_related("mineral")
    )
    mapped_layer_ids = set(
        layers_with_mapped_data(MapLayer.objects.filter(is_active=True, mineral__country=country)).values_list(
            "id", flat=True
        )
    )
    layer_counts = _feature_counts_by_layer(mapped_layer_ids)

    entries_by_slug: dict[str, dict] = {}

    minerals = Mineral.objects.filter(is_active=True, country=country).order_by("name")
    mineral_counts: dict[str, int] = {}
    if mapped_layer_ids:
        for mineral_slug in (
            MapFeature.objects.filter(is_active=True, layer_id__in=mapped_layer_ids)
            .values_list("layer__mineral__slug", flat=True)
        ):
            mineral_counts[mineral_slug] = mineral_counts.get(mineral_slug, 0) + 1

    for mineral in minerals:
        feature_count = mineral_counts.get(mineral.slug, 0)
        entries_by_slug[mineral.slug] = {
            "id": mineral.id,
            "slug": mineral.slug,
            "name": localized_name(mineral, locale),
            "name_sw": mineral.name_sw,
            "color": mineral.color,
            "description": mineral.description or "",
            "feature_count": feature_count,
            "is_mapped": feature_count > 0,
        }

    for periodic_slug in PERIODIC_LAYER_SLUGS:
        layer = _find_layer_for_catalog_slug(periodic_slug, layers)
        if not layer:
            continue
        entries_by_slug[periodic_slug] = _layer_catalog_entry(
            layer,
            slug=periodic_slug,
            feature_count=layer_counts.get(layer.id, 0),
            locale=locale,
        )

    for layer in layers:
        if layer.slug in entries_by_slug:
            continue
        entries_by_slug[layer.slug] = _layer_catalog_entry(
            layer,
            slug=layer.slug,
            feature_count=layer_counts.get(layer.id, 0),
            locale=locale,
        )

    return sorted(
        (_attach_periodic_fields(row) for row in entries_by_slug.values()),
        key=lambda row: row["name"].lower(),
    )


def mineral_catalog_stats(*, country_code: str = "TZ") -> dict:
    country = Country.objects.filter(code=country_code.upper()).first()
    if not country:
        return {"layer_count": 0, "mapped_layer_count": 0}

    layers_qs = MapLayer.objects.filter(is_active=True, mineral__country=country)
    mapped_ids = set(layers_with_mapped_data(layers_qs).values_list("id", flat=True))
    return {
        "layer_count": layers_qs.count(),
        "mapped_layer_count": len(mapped_ids),
    }


def build_mineral_boundary_coverage(
    mineral_slug: str,
    *,
    country_code: str = "TZ",
    user=None,
    include_villages: bool = False,
    max_features: int = 5000,
    locale: str = "en",
) -> dict | None:
    country = Country.objects.filter(code=country_code.upper()).first()
    if not country:
        return None

    layers = list(
        MapLayer.objects.filter(is_active=True, mineral__country=country).select_related("mineral")
    )
    layer = _find_layer_for_catalog_slug(mineral_slug, layers)
    if layer:
        features = list(_accessible_features(user).filter(layer=layer)[:max_features])
        display_name = localized_name(layer, locale)
        color = layer_display_color(layer)
        slug = mineral_slug
    else:
        try:
            mineral = Mineral.objects.get(slug=mineral_slug, is_active=True, country=country)
        except Mineral.DoesNotExist:
            return None
        features = list(_accessible_features(user, mineral_slug=mineral_slug)[:max_features])
        display_name = localized_name(mineral, locale)
        color = mineral.color
        slug = mineral.slug

    if not features:
        return {
            "slug": slug,
            "name": display_name,
            "color": color,
            "feature_count": 0,
            "region_ids": [],
            "district_ids": [],
            "village_ids": [],
            "bounds": None,
            "center": None,
        }

    region_ids: set[int] = set()
    district_ids: set[int] = set()
    village_ids: set[int] = set()
    lats: list[float] = []
    lngs: list[float] = []

    for feature in features:
        lat, lng = feature_sample_point(feature)
        if lat or lng:
            lats.append(lat)
            lngs.append(lng)
        hit = lookup_boundaries_at_point(country, lat, lng)
        region = hit.get("region")
        district = hit.get("district")
        village = hit.get("village")
        if region and region.get("id"):
            region_ids.add(int(region["id"]))
        if district and district.get("id"):
            district_ids.add(int(district["id"]))
        if include_villages and village and village.get("id"):
            village_ids.add(int(village["id"]))

    bounds = None
    center = None
    if lats and lngs:
        south, north = min(lats), max(lats)
        west, east = min(lngs), max(lngs)
        bounds = {"west": west, "south": south, "east": east, "north": north}
        center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
    else:
        boundary_ids = list(region_ids | district_ids | (village_ids if include_villages else set()))
        if boundary_ids:
            boxes = []
            for boundary in AdminBoundary.objects.filter(id__in=boundary_ids).only("geometry"):
                bbox = geometry_bbox(boundary.geometry)
                if bbox:
                    boxes.append(bbox)
            if boxes:
                south = min(b[0] for b in boxes)
                north = max(b[1] for b in boxes)
                west = min(b[2] for b in boxes)
                east = max(b[3] for b in boxes)
                bounds = {"west": west, "south": south, "east": east, "north": north}
                center = {"lat": (south + north) / 2, "lng": (west + east) / 2}

    return {
        "slug": slug,
        "name": display_name,
        "color": color,
        "feature_count": len(features),
        "region_ids": sorted(region_ids),
        "district_ids": sorted(district_ids),
        "village_ids": sorted(village_ids) if include_villages else [],
        "bounds": bounds,
        "center": center,
    }
