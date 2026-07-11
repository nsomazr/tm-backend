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

# Boundary hit-testing per feature is expensive; sample + cache for large layers.
BOUNDARY_LOOKUP_MAX_FEATURES = 250
BOUNDARY_LOOKUP_COORD_PRECISION = 3

# Periodic-table slugs → uploaded layer slug(s) on the platform.
PERIODIC_LAYER_SLUGS: dict[str, list[str]] = {
    "lithium": ["lithium", "lithium-points"],
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


def layers_for_catalog_slug(catalog_slug: str, *, country_code: str = "TZ") -> list[MapLayer]:
    """All map layers tied to a periodic-table / navbar commodity slug."""
    catalog_slug = (catalog_slug or "").strip()
    if not catalog_slug:
        return []

    country = Country.objects.filter(code=country_code.upper()).first()
    if not country:
        return []

    all_layers = list(
        MapLayer.objects.filter(is_active=True, mineral__country=country).select_related("mineral")
    )
    matched: list[MapLayer] = []
    seen: set[int] = set()

    def add(layer: MapLayer | None) -> None:
        if layer and layer.id not in seen:
            matched.append(layer)
            seen.add(layer.id)

    add(_find_layer_for_catalog_slug(catalog_slug, all_layers))

    for layer in all_layers:
        if layer.slug == catalog_slug:
            add(layer)
        elif layer.mineral_id and layer.mineral.slug == catalog_slug:
            add(layer)

    for candidate in PERIODIC_LAYER_SLUGS.get(catalog_slug, []):
        for layer in all_layers:
            if layer.slug == candidate:
                add(layer)

    mineral = Mineral.objects.filter(
        is_active=True, country=country, slug=catalog_slug
    ).prefetch_related("associated_layers").first()
    if mineral is None:
        # Periodic alias may map to a mineral with a different slug.
        for layer in matched:
            if layer.mineral_id:
                mineral = (
                    Mineral.objects.filter(pk=layer.mineral_id)
                    .prefetch_related("associated_layers")
                    .first()
                )
                if mineral:
                    break
    if mineral is not None:
        for layer in mineral.associated_layers.filter(is_active=True).select_related("mineral"):
            add(layer)

    return matched


def _even_sample_features(features: list, max_count: int = BOUNDARY_LOOKUP_MAX_FEATURES) -> list:
    if len(features) <= max_count:
        return features
    step = len(features) / max_count
    return [features[int(index * step)] for index in range(max_count)]


def _collect_boundary_ids_from_features(
    country: Country,
    features: list,
    *,
    include_villages: bool = False,
    include_wards: bool = False,
) -> tuple[set[int], set[int], set[int], set[int], list[float], list[float]]:
    region_ids: set[int] = set()
    district_ids: set[int] = set()
    ward_ids: set[int] = set()
    village_ids: set[int] = set()
    lats: list[float] = []
    lngs: list[float] = []
    cache: dict[tuple[float, float], dict] = {}

    for feature in features:
        lat, lng = feature_sample_point(feature)
        if lat or lng:
            lats.append(lat)
            lngs.append(lng)

    for feature in _even_sample_features(features):
        lat, lng = feature_sample_point(feature)
        if not lat and not lng:
            continue
        key = (
            round(lat, BOUNDARY_LOOKUP_COORD_PRECISION),
            round(lng, BOUNDARY_LOOKUP_COORD_PRECISION),
        )
        hit = cache.get(key)
        if hit is None:
            hit = lookup_boundaries_at_point(
                country,
                lat,
                lng,
                include_villages=include_villages,
                include_wards=include_wards,
            )
            cache[key] = hit

        region = hit.get("region")
        district = hit.get("district")
        ward = hit.get("ward")
        village = hit.get("village")
        if region and region.get("id"):
            region_ids.add(int(region["id"]))
        if district and district.get("id"):
            district_ids.add(int(district["id"]))
        if include_wards and ward and ward.get("id"):
            ward_ids.add(int(ward["id"]))
        if include_villages and village and village.get("id"):
            village_ids.add(int(village["id"]))

    return region_ids, district_ids, ward_ids, village_ids, lats, lngs


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
    style = layer.style or {}
    fill_rgba = style.get("fillRgba") if isinstance(style.get("fillRgba"), str) else ""
    if not fill_rgba and layer.mineral_id:
        fill_rgba = layer.mineral.color_rgba or ""
    return {
        "id": layer.id,
        "slug": slug,
        "name": localized_name(layer, locale),
        "name_sw": layer.name_sw or "",
        "color": layer_display_color(layer),
        "color_rgba": fill_rgba,
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


def _periodic_covered_layer_slugs(entries_by_slug: dict[str, dict]) -> set[str]:
    """Layer slugs already represented by a periodic-table catalog entry."""
    covered: set[str] = set()
    for periodic_slug, candidates in PERIODIC_LAYER_SLUGS.items():
        if periodic_slug not in entries_by_slug:
            continue
        covered.update(candidates)
    return covered


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
            "color_rgba": mineral.color_rgba or "",
            "description": mineral.description or "",
            "feature_count": feature_count,
            "is_mapped": feature_count > 0,
        }

    for periodic_slug in PERIODIC_LAYER_SLUGS:
        layer = _find_layer_for_catalog_slug(periodic_slug, layers)
        if not layer:
            continue
        if layer.mineral_id:
            mineral_slug = layer.mineral.slug
            if mineral_slug in entries_by_slug and mineral_slug != periodic_slug:
                entries_by_slug.pop(mineral_slug, None)
        entries_by_slug[periodic_slug] = _layer_catalog_entry(
            layer,
            slug=periodic_slug,
            feature_count=layer_counts.get(layer.id, 0),
            locale=locale,
        )

    periodic_covered = _periodic_covered_layer_slugs(entries_by_slug)

    for layer in layers:
        if layer.slug in entries_by_slug:
            continue
        if layer.slug in periodic_covered:
            continue
        if layer.mineral_id and layer.mineral.slug in entries_by_slug:
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
    catalog_layers = layers_for_catalog_slug(mineral_slug, country_code=country_code)
    if catalog_layers:
        features = []
        for layer in catalog_layers:
            features.extend(list(_accessible_features(user).filter(layer=layer)[:max_features]))
        features = features[:max_features]
        display_name = localized_name(catalog_layers[0], locale)
        color = layer_display_color(catalog_layers[0])
        for layer in catalog_layers:
            if layer.mineral_id and layer.mineral.slug == mineral_slug:
                display_name = localized_name(layer.mineral, locale)
                color = layer.mineral.color
                break
        slug = mineral_slug
    else:
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

    region_ids, district_ids, _ward_ids, village_ids, lats, lngs = _collect_boundary_ids_from_features(
        country,
        features,
        include_villages=include_villages,
        include_wards=False,
    )

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


def build_layers_boundary_coverage(
    layer_ids: list[int],
    *,
    country_code: str = "TZ",
    user=None,
    include_villages: bool = False,
    max_features: int = 5000,
) -> dict:
    """Map selected layer features to admin boundaries at region→village levels."""
    country = Country.objects.filter(code=country_code.upper()).first()
    if not country:
        return {
            "layer_ids": layer_ids,
            "feature_count": 0,
            "region_ids": [],
            "district_ids": [],
            "ward_ids": [],
            "village_ids": [],
            "bounds": None,
            "center": None,
        }

    if not layer_ids:
        return {
            "layer_ids": [],
            "feature_count": 0,
            "region_ids": [],
            "district_ids": [],
            "ward_ids": [],
            "village_ids": [],
            "bounds": None,
            "center": None,
        }

    layers = list(
        MapLayer.objects.filter(id__in=layer_ids, is_active=True, mineral__country=country).select_related(
            "region"
        )
    )
    if user and not getattr(user, "is_staff", False):
        from .insights import _accessible_layers

        allowed_ids = set(_accessible_layers(user).filter(id__in=layer_ids).values_list("id", flat=True))
        layers = [layer for layer in layers if layer.id in allowed_ids]

    features = list(
        _accessible_features(user)
        .filter(layer_id__in=[layer.id for layer in layers], is_active=True)[:max_features]
    )

    if not features:
        region_ids: set[int] = set()
        for layer in layers:
            if layer.region_id:
                region_ids.add(int(layer.region_id))
        catalog_region_boundary_ids: list[int] = []
        if region_ids:
            catalog_region_boundary_ids = list(
                AdminBoundary.objects.filter(
                    country=country, level=1, region_id__in=region_ids
                ).values_list("id", flat=True)
            )
            if not catalog_region_boundary_ids:
                names = [layer.region.name for layer in layers if layer.region_id and layer.region]
                for name in names:
                    match = AdminBoundary.objects.filter(
                        country=country, level=1, name__iexact=name
                    ).first()
                    if match:
                        catalog_region_boundary_ids.append(match.id)

        return {
            "layer_ids": [layer.id for layer in layers],
            "feature_count": 0,
            "region_ids": sorted(set(catalog_region_boundary_ids)),
            "district_ids": [],
            "ward_ids": [],
            "village_ids": [],
            "bounds": None,
            "center": None,
        }

    region_ids, district_ids, ward_ids, village_ids, lats, lngs = _collect_boundary_ids_from_features(
        country,
        features,
        include_villages=include_villages,
        include_wards=True,
    )

    bounds = None
    center = None
    if lats and lngs:
        south, north = min(lats), max(lats)
        west, east = min(lngs), max(lngs)
        bounds = {"west": west, "south": south, "east": east, "north": north}
        center = {"lat": sum(lats) / len(lats), "lng": sum(lngs) / len(lngs)}
    else:
        boundary_ids = list(region_ids | district_ids | ward_ids | (village_ids if include_villages else set()))
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
        "layer_ids": [layer.id for layer in layers],
        "feature_count": len(features),
        "region_ids": sorted(region_ids),
        "district_ids": sorted(district_ids),
        "ward_ids": sorted(ward_ids),
        "village_ids": sorted(village_ids) if include_villages else [],
        "bounds": bounds,
        "center": center,
    }
