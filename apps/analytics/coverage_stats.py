"""Spatial coverage stats: assign prospect zones to admin regions and uploaded layers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.db.models import Count, Q

from apps.geography.admin_boundary_service import _geometry_centroid
from apps.geography.models import AdminBoundary, Country
from apps.maps.access import layers_with_mapped_data
from apps.maps.geometry_utils import geometry_area_km2, geometry_bbox, point_in_geometry
from apps.maps.layer_defaults import GENERAL_MINERAL_SLUG
from apps.maps.localization import localized_name
from apps.maps.models import MapFeature, MapLayer

from .spatial_assign import AdminBoundaryIndex, feature_sample_point, layer_display_color

_ACTIVE_FEATURE = Q(features__is_active=True)

# Analytics tracks mineral coverage only (polygons + points). Structure lines stay on the map/heatmap.
ANALYTICS_LAYER_TYPES = (MapLayer.LayerType.POLYGON, MapLayer.LayerType.POINT)


def analytics_features_qs(features_qs=None):
    """Active features on polygon/point layers (excludes structure lines)."""
    qs = features_qs if features_qs is not None else MapFeature.objects.all()
    return qs.filter(
        is_active=True,
        layer__is_active=True,
        layer__layer_type__in=ANALYTICS_LAYER_TYPES,
    )


def analytics_layers_qs(layers_qs=None):
    """Active polygon/point layers with mapped data (excludes structure lines)."""
    qs = layers_qs if layers_qs is not None else MapLayer.objects.all()
    return layers_with_mapped_data(
        qs.filter(is_active=True, layer_type__in=ANALYTICS_LAYER_TYPES)
    )


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


def _mineral_hotspot_group_key(row: dict[str, Any]) -> str:
    """Group key for mineral-level hotspot rows.

    Dedicated minerals merge polygon/point layers. Layers still on the shared
    ``general`` mineral stay separate (layer slug) so each upload appears in selectors.
    """
    mineral_slug = row.get("mineral_slug") or row["slug"]
    if mineral_slug == GENERAL_MINERAL_SLUG:
        return row["slug"]
    return mineral_slug


def _aggregate_mineral_hotspots(layer_hotspots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per commodity mineral (sum polygon/point layers for the same mineral)."""
    merged: dict[str, dict[str, Any]] = {}
    for row in layer_hotspots:
        mineral_slug = row.get("mineral_slug") or row["slug"]
        mineral_name = row.get("mineral_name") or row["name"]
        group_key = _mineral_hotspot_group_key(row)
        if group_key not in merged:
            use_layer_identity = mineral_slug == GENERAL_MINERAL_SLUG
            merged[group_key] = {
                "slug": row["slug"] if use_layer_identity else mineral_slug,
                "name": row["name"] if use_layer_identity else mineral_name,
                "name_sw": (
                    row.get("name_sw") or row["name"]
                    if use_layer_identity
                    else row.get("mineral_name_sw") or row.get("name_sw") or mineral_name
                ),
                "color": row["color"],
                "feature_count": 0,
                "layer_type": "mineral",
                "hotspots": {},
            }
            if row.get("area_km2"):
                merged[group_key]["area_km2"] = 0.0

        entry = merged[group_key]
        entry["feature_count"] += row["feature_count"]
        if row.get("area_km2"):
            entry["area_km2"] = entry.get("area_km2", 0.0) + row["area_km2"]

        region_map: dict[str, dict[str, Any]] = entry["hotspots"]
        for region_row in row.get("hotspots") or []:
            region = region_row["region"]
            if region not in region_map:
                region_map[region] = {
                    "region": region,
                    "feature_count": 0,
                }
            region_map[region]["feature_count"] += region_row["feature_count"]
            if region_row.get("area_km2"):
                region_map[region]["area_km2"] = (
                    region_map[region].get("area_km2", 0.0) + region_row["area_km2"]
                )

    mineral_hotspots = []
    for entry in merged.values():
        hotspots = sorted(
            [
                {
                    **row,
                    **({"area_km2": round(row["area_km2"], 2)} if row.get("area_km2") else {}),
                }
                for row in entry["hotspots"].values()
            ],
            key=lambda row: row["feature_count"],
            reverse=True,
        )[:10]
        payload = {
            "slug": entry["slug"],
            "name": entry["name"],
            "name_sw": entry["name_sw"],
            "color": entry["color"],
            "feature_count": entry["feature_count"],
            "layer_type": entry["layer_type"],
            "hotspots": hotspots,
        }
        if entry.get("area_km2"):
            payload["area_km2"] = round(entry["area_km2"], 2)
        mineral_hotspots.append(payload)

    mineral_hotspots.sort(key=lambda row: row["feature_count"], reverse=True)
    return mineral_hotspots


def build_feature_coverage_stats(
    features_qs,
    *,
    country_code: str = "TZ",
    locale: str = "en",
    max_features: int | None = None,
) -> dict[str, Any]:
    features_qs = analytics_features_qs(features_qs)
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

    total_prospects = features_qs.count()
    feature_stream = features_qs.select_related("layer", "layer__mineral", "layer__region")
    if max_features is not None:
        feature_stream = feature_stream[:max_features]

    for feature in feature_stream.iterator(chunk_size=2000):
        layer = feature.layer
        mineral = layer.mineral
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
                "mineral_slug": mineral.slug,
                "mineral_name": localized_name(mineral, locale),
                "mineral_name_sw": mineral.name_sw,
            }

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
    mineral_hotspots = _aggregate_mineral_hotspots(layer_hotspots)

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
        "mineral_hotspots": mineral_hotspots,
        "layers": layers,
        "minerals": minerals,
        "total_prospects": total_prospects,
    }
    if total_area_km2 > 0:
        payload["total_area_km2"] = round(total_area_km2, 2)
    return payload


def build_layer_inventory(*, locale: str = "en") -> list[dict[str, Any]]:
    rows = []
    for layer in (
        analytics_layers_qs()
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
    max_features: int | None = None,
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
