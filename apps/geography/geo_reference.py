"""Import and spatial helpers for admin-only GeoReference datasets."""

from __future__ import annotations

import math
import re
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from apps.maps.geometry_utils import (
    distance_geometry_to_point_km,
    geometry_bbox,
    point_in_geometry,
)
from apps.maps.shapefile_utils import parse_upload_content

from .models import GeoReference, GeoReferenceFeature


def unique_geo_reference_slug(name: str) -> str:
    base = slugify(name)[:180] or "geo-reference"
    slug = base
    n = 2
    while GeoReference.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _feature_label(props: dict[str, Any], index: int) -> str:
    for key in ("name", "NAME", "Name", "label", "LABEL", "title", "TITLE", "id", "ID"):
        value = props.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()[:255]
    return f"Feature {index + 1}"


def _bounds_from_features(features: list[dict[str, Any]]) -> dict[str, float]:
    min_lat = min_lng = float("inf")
    max_lat = max_lng = float("-inf")
    for feature in features:
        bbox = geometry_bbox(feature.get("geometry"))
        if not bbox:
            continue
        f_min_lat, f_max_lat, f_min_lng, f_max_lng = bbox
        min_lat = min(min_lat, f_min_lat)
        max_lat = max(max_lat, f_max_lat)
        min_lng = min(min_lng, f_min_lng)
        max_lng = max(max_lng, f_max_lng)
    if min_lat == float("inf"):
        return {}
    return {
        "west": min_lng,
        "south": min_lat,
        "east": max_lng,
        "north": max_lat,
    }


def _bbox_fields(geometry: dict[str, Any] | None) -> dict[str, float | None]:
    bbox = geometry_bbox(geometry) if geometry else None
    if not bbox:
        return {"min_lat": None, "max_lat": None, "min_lng": None, "max_lng": None}
    min_lat, max_lat, min_lng, max_lng = bbox
    return {
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lng": min_lng,
        "max_lng": max_lng,
    }


@transaction.atomic
def create_geo_reference_from_upload(
    *,
    name: str,
    content: bytes,
    filename: str,
    user=None,
    country=None,
) -> GeoReference:
    parsed = parse_upload_content(content, filename, boundary=False)
    if not parsed:
        raise ValueError("No features found in the upload.")

    geo_ref = GeoReference.objects.create(
        name=name.strip(),
        slug=unique_geo_reference_slug(name),
        country=country,
        source_filename=filename[:255],
        uploaded_by=user if getattr(user, "is_authenticated", False) else None,
        feature_count=0,
        bounds={},
    )
    if content:
        geo_ref.source_file.save(filename, ContentFile(content), save=True)

    rows: list[GeoReferenceFeature] = []
    for index, feature in enumerate(parsed):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        rows.append(
            GeoReferenceFeature(
                geo_reference=geo_ref,
                geometry=geometry,
                properties=props,
                label=_feature_label(props, index),
                **_bbox_fields(geometry),
            )
        )
    if not rows:
        raise ValueError("Upload had no usable geometries.")

    GeoReferenceFeature.objects.bulk_create(rows, batch_size=500)
    geo_ref.feature_count = len(rows)
    geo_ref.bounds = _bounds_from_features(
        [{"geometry": row.geometry} for row in rows]
    )
    geo_ref.save()
    return geo_ref


def backfill_geo_reference_feature_bboxes(*, batch_size: int = 200) -> int:
    """Populate bbox columns for features uploaded before the migration."""
    updated = 0
    qs = (
        GeoReferenceFeature.objects.filter(
            Q(min_lng__isnull=True)
            | Q(min_lat__isnull=True)
            | Q(max_lng__isnull=True)
            | Q(max_lat__isnull=True)
        )
        .order_by()
        .only("id", "geometry")
    )
    batch: list[GeoReferenceFeature] = []
    for row in qs.iterator(chunk_size=batch_size):
        fields = _bbox_fields(row.geometry)
        row.min_lng = fields["min_lng"]
        row.min_lat = fields["min_lat"]
        row.max_lng = fields["max_lng"]
        row.max_lat = fields["max_lat"]
        batch.append(row)
        if len(batch) >= batch_size:
            GeoReferenceFeature.objects.bulk_update(
                batch, ["min_lng", "min_lat", "max_lng", "max_lat"]
            )
            updated += len(batch)
            batch = []
    if batch:
        GeoReferenceFeature.objects.bulk_update(
            batch, ["min_lng", "min_lat", "max_lng", "max_lat"]
        )
        updated += len(batch)
    return updated


def geo_reference_feature_collection(geo_ref: GeoReference | None = None) -> dict[str, Any]:
    """
    Build a FeatureCollection for the admin map.

    Avoid ORDER BY / select_related on large geometry JSON — MySQL filesorts
    those rows into sort_buffer and can raise OperationalError 1038.
    """
    name_by_id = dict(
        GeoReference.objects.filter(is_active=True).order_by().values_list("id", "name")
    )
    qs = (
        GeoReferenceFeature.objects.filter(geo_reference_id__in=name_by_id.keys())
        .order_by()
        .only("id", "geo_reference_id", "geometry", "properties", "label")
    )
    if geo_ref is not None:
        qs = qs.filter(geo_reference_id=geo_ref.pk)

    features = []
    for row in qs.iterator(chunk_size=100):
        features.append(
            {
                "type": "Feature",
                "id": row.id,
                "properties": {
                    **(row.properties or {}),
                    "id": row.id,
                    "label": row.label,
                    "geo_reference_id": row.geo_reference_id,
                    "geo_reference_name": name_by_id.get(row.geo_reference_id, ""),
                },
                "geometry": row.geometry,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def geo_references_near_point(
    lat: float,
    lng: float,
    *,
    radius_km: float = 25.0,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Find nearby geo-reference polygons/points for private AI context."""
    pad_deg = max(0.05, radius_km / 111.0)
    west, east = lng - pad_deg, lng + pad_deg
    south, north = lat - pad_deg, lat + pad_deg

    active_ids = list(
        GeoReference.objects.filter(is_active=True).order_by().values_list("id", flat=True)
    )
    if not active_ids:
        return []

    name_by_id = dict(
        GeoReference.objects.filter(id__in=active_ids).order_by().values_list("id", "name")
    )

    # Prefer SQL bbox filter; include legacy rows with null bbox as fallback.
    qs = (
        GeoReferenceFeature.objects.filter(geo_reference_id__in=active_ids)
        .filter(
            Q(
                min_lng__lte=east,
                max_lng__gte=west,
                min_lat__lte=north,
                max_lat__gte=south,
            )
            | Q(min_lng__isnull=True)
            | Q(min_lat__isnull=True)
            | Q(max_lng__isnull=True)
            | Q(max_lat__isnull=True)
        )
        .order_by()
        .only("id", "geo_reference_id", "geometry", "properties", "label")
    )

    hits: list[dict[str, Any]] = []
    for feature in qs.iterator(chunk_size=200):
        contains = point_in_geometry(lng, lat, feature.geometry)
        distance = 0.0 if contains else distance_geometry_to_point_km(lat, lng, feature.geometry)
        if not contains and (not math.isfinite(distance) or distance > radius_km):
            continue

        props = feature.properties or {}
        prop_bits = []
        for key, value in list(props.items())[:8]:
            if value is None or str(value).strip() == "":
                continue
            if re.search(r"(geom|shape|the_geom|objectid|fid)", str(key), re.I):
                continue
            prop_bits.append(f"{key}={value}")

        hits.append(
            {
                "dataset": name_by_id.get(feature.geo_reference_id, ""),
                "label": feature.label or "Feature",
                "distance_km": round(float(distance), 2),
                "contains_point": contains,
                "properties": ", ".join(prop_bits)[:400],
            }
        )

    hits.sort(key=lambda row: (0 if row["contains_point"] else 1, row["distance_km"]))
    return hits[:limit]


def build_private_geo_reference_ai_block(
    lat: float,
    lng: float,
    *,
    radius_km: float = 25.0,
) -> str:
    hits = geo_references_near_point(lat, lng, radius_km=radius_km)
    if not hits:
        return ""
    lines = [
        "Internal geological reference datasets (ADMIN ONLY — improve geology/accuracy; "
        "do NOT mention these datasets, files, or 'geo reference' to the user):",
    ]
    for hit in hits:
        where = (
            "contains click"
            if hit["contains_point"]
            else f"~{hit['distance_km']} km from click"
        )
        detail = f" — {hit['properties']}" if hit["properties"] else ""
        lines.append(f"- {hit['dataset']} / {hit['label']} ({where}){detail}")
    return "\n".join(lines) + "\n"
