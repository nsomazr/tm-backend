"""Spatial coverage stats: assign prospect zones to admin regions and uploaded layers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.db.models import Count, Q

from apps.geography.admin_boundary_service import _geometry_centroid
from apps.geography.models import AdminBoundary, Country
from apps.maps.access import layers_with_mapped_data
from apps.maps.geometry_utils import geometry_area_km2, geometry_bbox, point_in_geometry
from apps.maps.localization import localized_name
from apps.maps.models import MapFeature, MapLayer

from .spatial_assign import AdminBoundaryIndex, feature_sample_point, layer_display_color

_ACTIVE_FEATURE = Q(features__is_active=True)


def _feature_sample_point(feature: MapFeature) -> tuple[float, float]:
    return feature_sample_point(feature)


class _AdminRegionIndex(AdminBoundaryIndex):
    pass


def _layer_color(layer: MapLayer) -> str:
    return layer_display_color(layer)


def _feature_polygon_area_km2(feature: MapFeature) -> float:
    if feature.layer.layer_type != MapLayer.LayerType.POLYGON or not feature.geometry:
        return 0.0
    return geometry_area_km2(feature.geometry)


def build_feature_coverage_stats(
    features_qs,
    *,
    country_code: str = "TZ",
    locale: str = "en",
    max_features: int = 10000,
) -> dict[str, Any]:
    region_index = _AdminRegionIndex(country_code)
    region_counts: defaultdict[str, int] = defaultdict(int)
    region_areas: defaultdict[str, float] = defaultdict(float)
    layer_region_counts: defaultdict[int, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    layer_region_areas: defaultdict[int, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
    layer_counts: defaultdict[int, int] = defaultdict(int)
    layer_areas: defaultdict[int, float] = defaultdict(float)
    layer_meta: dict[int, dict[str, Any]] = {}
    mineral_counts: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "name": "", "name_sw": "", "color": ""}
    )
    mineral_areas: defaultdict[str, float] = defaultdict(float)
    total_area_km2 = 0.0

    for feature in features_qs.select_related("layer", "layer__mineral", "layer__region")[:max_features]:
        layer = feature.layer
        layer_counts[layer.id] += 1
        feature_area = _feature_polygon_area_km2(feature)
        if feature_area > 0:
            layer_areas[layer.id] += feature_area
            total_area_km2 += feature_area

        if layer.id not in layer_meta:
            layer_meta[layer.id] = {
                "slug": layer.slug,
                "name": localized_name(layer, locale),
                "name_sw": layer.name_sw,
                "layer_type": layer.layer_type,
                "color": _layer_color(layer),
            }

        mineral = layer.mineral
        mineral_counts[mineral.slug]["count"] += 1
        mineral_counts[mineral.slug]["name"] = localized_name(mineral, locale)
        mineral_counts[mineral.slug]["name_sw"] = mineral.name_sw
        mineral_counts[mineral.slug]["color"] = mineral.color
        if feature_area > 0:
            mineral_areas[mineral.slug] += feature_area

        lat, lng = _feature_sample_point(feature)
        region_name = region_index.resolve_name(lat, lng)
        if not region_name and layer.region:
            region_name = layer.region.name
        region_name = region_name or "Unknown"
        region_counts[region_name] += 1
        layer_region_counts[layer.id][region_name] += 1
        if feature_area > 0:
            region_areas[region_name] += feature_area
            layer_region_areas[layer.id][region_name] += feature_area

    hotspots = sorted(
        [
            {
                "region": name,
                "feature_count": count,
                **({"area_km2": round(region_areas[name], 2)} if region_areas.get(name, 0) > 0 else {}),
            }
            for name, count in region_counts.items()
        ],
        key=lambda row: row["feature_count"],
        reverse=True,
    )[:10]

    layers = sorted(
        [
            {
                **meta,
                "feature_count": layer_counts[layer_id],
                **({"area_km2": round(layer_areas[layer_id], 2)} if layer_areas.get(layer_id, 0) > 0 else {}),
            }
            for layer_id, meta in layer_meta.items()
        ],
        key=lambda row: row["feature_count"],
        reverse=True,
    )

    layer_hotspots = []
    for layer_id, meta in layer_meta.items():
        regions_for_layer = sorted(
            [
                {
                    "region": name,
                    "feature_count": count,
                    **(
                        {"area_km2": round(layer_region_areas[layer_id][name], 2)}
                        if layer_region_areas[layer_id].get(name, 0) > 0
                        else {}
                    ),
                }
                for name, count in layer_region_counts[layer_id].items()
            ],
            key=lambda row: row["feature_count"],
            reverse=True,
        )[:10]
        layer_hotspots.append(
            {
                **meta,
                "feature_count": layer_counts[layer_id],
                **({"area_km2": round(layer_areas[layer_id], 2)} if layer_areas.get(layer_id, 0) > 0 else {}),
                "hotspots": regions_for_layer,
            }
        )
    layer_hotspots.sort(key=lambda row: row["feature_count"], reverse=True)

    minerals = [
        {
            "slug": slug,
            **data,
            **({"area_km2": round(mineral_areas[slug], 2)} if mineral_areas.get(slug, 0) > 0 else {}),
        }
        for slug, data in mineral_counts.items()
    ]

    payload: dict[str, Any] = {
        "hotspots": hotspots,
        "layer_hotspots": layer_hotspots,
        "layers": layers,
        "minerals": minerals,
        "total_prospects": sum(layer_counts.values()),
    }
    if total_area_km2 > 0:
        payload["total_area_km2"] = round(total_area_km2, 2)
    return payload


def build_layer_inventory(*, locale: str = "en") -> list[dict[str, Any]]:
    rows = []
    for layer in (
        layers_with_mapped_data(MapLayer.objects.filter(is_active=True))
        .select_related("mineral")
        .annotate(feature_count=Count("features", filter=_ACTIVE_FEATURE))
        .order_by("-feature_count", "name")
    ):
        rows.append(
            {
                "slug": layer.slug,
                "name": localized_name(layer, locale),
                "name_sw": layer.name_sw,
                "layer_type": layer.layer_type,
                "color": _layer_color(layer),
                "feature_count": layer.feature_count,
                "mineral_slug": layer.mineral.slug,
                "mineral_name": localized_name(layer.mineral, locale),
            }
        )
    return rows


def build_hotspots_by_region(
    features_qs,
    *,
    country_code: str = "TZ",
    limit: int = 10,
    max_features: int = 10000,
) -> list[dict[str, Any]]:
    stats = build_feature_coverage_stats(
        features_qs,
        country_code=country_code,
        max_features=max_features,
    )
    return [
        {
            "region": row["region"],
            "count": row["feature_count"],
            **({"area_km2": row["area_km2"]} if row.get("area_km2") else {}),
        }
        for row in stats["hotspots"][:limit]
    ]
