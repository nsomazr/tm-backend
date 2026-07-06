"""Import, query, and point lookup for administrative boundary polygons."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Callable

from django.conf import settings
from django.db import transaction

from apps.maps.geometry_utils import geometry_bbox, point_in_geometry
from apps.maps.crs_utils import ensure_wgs84_geometry
from apps.maps.upload_security import friendly_upload_error

from .country_geo import preset_for_code
from .models import AdminBoundary, Country, Region
from .region_geo import REGION_CENTERS, region_bounds


def boundaries_data_dir() -> Path:
    return Path(settings.BASE_DIR) / "sample_data" / "boundaries"


def friendly_boundary_import_error(exc: Exception) -> str:
    """Turn low-level OS/DB failures into a short message for the admin UI."""
    return friendly_upload_error(exc)


def _slug_code(value: str, fallback: str = "area") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (value or fallback).strip()).strip("_").lower()
    return slug[:60] or fallback


def _composite_code(props: dict[str, Any], *field_names: str) -> str:
    """Build a stable hierarchical code from shapefile columns (e.g. Region_Cod-District_C-Ward_Code)."""
    parts: list[str] = []
    for key in field_names:
        val = props.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            parts.append(text)
    return "-".join(parts)


def _parent_lookup_key(props: dict[str, Any], level: int) -> str:
    if level == 2:
        return _composite_code(props, "Region_Cod") or str(props.get("GID_1") or props.get("NAME_1") or "").strip()
    if level == 3:
        return (
            _composite_code(props, "Region_Cod", "District_C")
            or str(props.get("GID_2") or props.get("NAME_2") or "").strip()
        )
    if level == 4:
        return (
            _composite_code(props, "Region_Cod", "District_C", "Ward_Code")
            or str(props.get("GID_3") or props.get("NAME_3") or props.get("Ward_Name") or "").strip()
        )
    return ""


def _bbox_ring(bounds: dict[str, float]) -> list[list[float]]:
    west, east = bounds["west"], bounds["east"]
    south, north = bounds["south"], bounds["north"]
    return [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
    ]


def _ring_centroid(ring: list[list[float]]) -> tuple[float, float]:
    if not ring:
        return 0.0, 0.0
    lngs = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return sum(lats) / len(lats), sum(lngs) / len(lngs)


def _geometry_centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon" and coords:
        return _ring_centroid(coords[0])
    if gtype == "MultiPolygon" and coords and coords[0]:
        return _ring_centroid(coords[0][0])
    bbox = geometry_bbox(geometry)
    if bbox:
        min_lat, max_lat, min_lng, max_lng = bbox
        return (min_lat + max_lat) / 2, (min_lng + max_lng) / 2
    return 0.0, 0.0


def _thin_ring(ring: list[list[float]], min_dist_deg: float = 0.02) -> list[list[float]]:
    if len(ring) <= 8:
        return ring
    out = [ring[0]]
    for pt in ring[1:]:
        prev = out[-1]
        if math.hypot(pt[0] - prev[0], pt[1] - prev[1]) >= min_dist_deg:
            out.append(pt)
    if out[-1] != ring[-1]:
        out.append(ring[-1])
    return out


def _display_ring(ring: list[list[float]], max_points: int = 12) -> list[list[float]]:
    """Sample polygon rings for map display (keeps endpoints, caps vertex count)."""
    if len(ring) <= max_points:
        return ring
    step = max(1, (len(ring) - 1) // (max_points - 1))
    out = [ring[i] for i in range(0, len(ring) - 1, step)]
    if out[-1] != ring[-1]:
        out.append(ring[-1])
    return out


def display_geometry(geometry: dict[str, Any], max_points: int = 12) -> dict[str, Any]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return geometry
    if gtype == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [_display_ring(ring, max_points) for ring in coords],
        }
    if gtype == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [_display_ring(ring, max_points) for ring in poly] for poly in coords
            ],
        }
    return geometry


def simplify_geometry(geometry: dict[str, Any], tolerance_deg: float = 0.015) -> dict[str, Any]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return geometry
    if gtype == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [_thin_ring(ring, tolerance_deg) for ring in coords],
        }
    if gtype == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [_thin_ring(ring, tolerance_deg) for ring in poly] for poly in coords
            ],
        }
    return geometry


def _extract_name_code(props: dict[str, Any], level: int) -> tuple[str, str]:
    props = props or {}
    if level == 0:
        name = props.get("COUNTRY") or props.get("NAME_0") or props.get("name") or "Country"
        code = props.get("GID_0") or props.get("ISO") or _slug_code(name)
    elif level == 1:
        name = (
            props.get("NAME_1")
            or props.get("Region_Nam")
            or props.get("REGION")
            or props.get("name")
            or props.get("region")
            or "Region"
        )
        code = (
            props.get("GID_1")
            or props.get("Region_Cod")
            or props.get("HASC_1")
            or _slug_code(name)
        )
    elif level == 2:
        name = (
            props.get("NAME_2")
            or props.get("District_N")
            or props.get("District_Nam")
            or props.get("DISTRICT")
            or props.get("name")
            or props.get("district")
            or "District"
        )
        name = str(name).strip()
        composite = _composite_code(props, "Region_Cod", "District_C")
        if props.get("GID_2"):
            code = str(props["GID_2"]).strip()
        elif props.get("HASC_2"):
            code = str(props["HASC_2"]).strip()
        elif composite:
            code = composite
        else:
            # District_C is only unique within a region, not nationally.
            code = _slug_code(name)
    elif level == 3:
        name = (
            props.get("NAME_3")
            or props.get("WARD")
            or props.get("Ward_Name")
            or props.get("Ward_Nam")
            or props.get("ward")
            or props.get("name")
            or "Ward"
        )
        code = (
            props.get("GID_3")
            or props.get("HASC_3")
            or _composite_code(props, "Region_Cod", "District_C", "Ward_Code")
            or _slug_code(name)
        )
    else:
        name = (
            props.get("NAME_4")
            or props.get("VILLAGE")
            or props.get("Vil_Mtaa_N")
            or props.get("Village_Nam")
            or props.get("village")
            or props.get("name")
            or "Village"
        )
        name = str(name).strip()
        composite = _composite_code(props, "Region_Cod", "District_C", "Ward_Code", "Vil_Mtaa_C")
        if props.get("GID_4"):
            code = str(props["GID_4"]).strip()
        elif props.get("HASC_4"):
            code = str(props["HASC_4"]).strip()
        elif composite:
            code = f"{composite}-{_slug_code(name)}"
        else:
            code = _slug_code(name)
    return str(name).strip(), str(code).strip()


def _match_region(country: Country, name: str) -> Region | None:
    if not name:
        return None
    region = Region.objects.filter(country=country, name__iexact=name.strip()).first()
    if region:
        return region
    return Region.objects.filter(country=country, name_sw__iexact=name.strip()).first()


def _upsert_boundary(
    *,
    country: Country,
    level: int,
    name: str,
    code: str,
    geometry: dict[str, Any],
    source: str,
    parent: AdminBoundary | None = None,
    name_sw: str = "",
) -> AdminBoundary:
    lat, lng = _geometry_centroid(geometry)
    region = _match_region(country, name) if level == 1 else None
    obj, _ = AdminBoundary.objects.update_or_create(
        country=country,
        level=level,
        code=code,
        defaults={
            "name": name,
            "name_sw": name_sw or name,
            "geometry": simplify_geometry(geometry, tolerance_deg=0.02 if level == 2 else 0.015),
            "source": source,
            "parent": parent,
            "region": region,
            "center_lat": lat,
            "center_lng": lng,
        },
    )
    return obj


def _features_from_geojson(data: dict[str, Any]) -> list[dict[str, Any]]:
    if data.get("type") == "FeatureCollection":
        return list(data.get("features") or [])
    if data.get("type") == "Feature":
        return [data]
    if data.get("type") in ("Polygon", "MultiPolygon"):
        return [{"type": "Feature", "properties": {}, "geometry": data}]
    return []


def import_features_for_country(
    country: Country,
    level: int,
    features: list[dict[str, Any]],
    *,
    source: str,
    replace: bool = False,
    progress_cb: Callable[[int, int], None] | None = None,
) -> int:
    if replace:
        AdminBoundary.objects.filter(country=country, level=level).exclude(
            source=AdminBoundary.Source.ADMIN_UPLOAD
        ).delete()
        if source == AdminBoundary.Source.ADMIN_UPLOAD:
            AdminBoundary.objects.filter(country=country, level=level).delete()

        parent_by_code: dict[str, AdminBoundary] = {}
        if level == 1:
            parent_by_code = {
                b.code: b
                for b in AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.COUNTRY)
            }
        elif level == 2:
            parent_by_code = {
                b.code: b
                for b in AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.REGION)
            }
        elif level == 3:
            parent_by_code = {
                b.code: b
                for b in AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.DISTRICT)
            }
        elif level == 4:
            parent_by_code = {
                b.code: b
                for b in AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.WARD)
            }

        region_parents: list[AdminBoundary] = []
        region_by_name: dict[str, AdminBoundary] = {}
        parent_by_name: dict[str, AdminBoundary] = {}
        if level == 2:
            region_parents = list(
                AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.REGION)
            )
            region_by_name = {b.name.lower(): b for b in region_parents}
        elif level == 3:
            parents = AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.DISTRICT)
            parent_by_name = {b.name.lower(): b for b in parents}
        elif level == 4:
            parents = AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.WARD)
            parent_by_name = {b.name.lower(): b for b in parents}

        total = len(features)
        boundaries_by_code: dict[str, AdminBoundary] = {}
        for index, feat in enumerate(features, start=1):
            geom = feat.get("geometry")
            if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
                if progress_cb and (index % 50 == 0 or index == total):
                    progress_cb(index, total)
                continue
            geom = ensure_wgs84_geometry(geom) or geom
            props = feat.get("properties") or {}
            name, code = _extract_name_code(props, level)
            if not code:
                if progress_cb and (index % 50 == 0 or index == total):
                    progress_cb(index, total)
                continue

            parent = None
            region = None
            if level == 1:
                parent_code = props.get("GID_0") or country.code
                parent = parent_by_code.get(str(parent_code))
            elif level == 2:
                parent_key = _parent_lookup_key(props, 2)
                parent = parent_by_code.get(parent_key)
                if not parent and props.get("NAME_1"):
                    parent = region_by_name.get(str(props["NAME_1"]).lower())
                if not parent and props.get("Region_Nam"):
                    parent = region_by_name.get(str(props["Region_Nam"]).lower())
                if not parent:
                    lat, lng = _geometry_centroid(geom)
                    for region in region_parents:
                        if point_in_geometry(lng, lat, region.geometry):
                            parent = region
                            break
            elif level == 3:
                parent_key = _parent_lookup_key(props, 3)
                parent = parent_by_code.get(parent_key)
                if not parent and props.get("NAME_2"):
                    parent = parent_by_name.get(str(props["NAME_2"]).lower())
                if not parent and props.get("District_N"):
                    parent = parent_by_name.get(str(props["District_N"]).lower())
            elif level == 4:
                parent_key = _parent_lookup_key(props, 4)
                parent = parent_by_code.get(parent_key)
                if not parent and props.get("NAME_3"):
                    parent = parent_by_name.get(str(props["NAME_3"]).lower())
                if not parent and props.get("Ward_Name"):
                    parent = parent_by_name.get(str(props["Ward_Name"]).lower())

            if level == 1:
                region = None
            elif level == 2:
                region = parent
            elif level in (3, 4):
                region = parent.region if parent else None

            lat, lng = _geometry_centroid(geom)
            boundary = AdminBoundary(
                country=country,
                level=level,
                name=name,
                name_sw=str(props.get("name_sw") or name),
                code=code,
                geometry=simplify_geometry(geom, tolerance_deg=0.02 if level == 2 else 0.015),
                source=source,
                parent=parent,
                region=region,
                center_lat=lat,
                center_lng=lng,
            )
            boundaries_by_code[code] = boundary
            if progress_cb and (index % 50 == 0 or index == total):
                progress_cb(index, total)

        if boundaries_by_code:
            AdminBoundary.objects.bulk_create(
                list(boundaries_by_code.values()),
                batch_size=500,
            )
        count = len(boundaries_by_code)
    else:
        parent_by_code: dict[str, AdminBoundary] = {}
        if level == 1:
            parent_by_code = {
                b.code: b
                for b in AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.COUNTRY)
            }
        elif level == 2:
            parent_by_code = {
                b.code: b
                for b in AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.REGION)
            }
        elif level == 3:
            parent_by_code = {
                b.code: b
                for b in AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.DISTRICT)
            }
        elif level == 4:
            parent_by_code = {
                b.code: b
                for b in AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.WARD)
            }

        region_parents: list[AdminBoundary] = []
        region_by_name: dict[str, AdminBoundary] = {}
        parent_by_name: dict[str, AdminBoundary] = {}
        if level == 2:
            region_parents = list(
                AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.REGION)
            )
            region_by_name = {b.name.lower(): b for b in region_parents}
        elif level == 3:
            parents = AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.DISTRICT)
            parent_by_name = {b.name.lower(): b for b in parents}
        elif level == 4:
            parents = AdminBoundary.objects.filter(country=country, level=AdminBoundary.Level.WARD)
            parent_by_name = {b.name.lower(): b for b in parents}

        total = len(features)
        count = 0
        for index, feat in enumerate(features, start=1):
            geom = feat.get("geometry")
            if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
                if progress_cb and (index % 50 == 0 or index == total):
                    progress_cb(index, total)
                continue
            geom = ensure_wgs84_geometry(geom) or geom
            props = feat.get("properties") or {}
            name, code = _extract_name_code(props, level)
            parent = None
            if level == 1:
                parent_code = props.get("GID_0") or country.code
                parent = parent_by_code.get(str(parent_code))
            elif level == 2:
                parent_key = _parent_lookup_key(props, 2)
                parent = parent_by_code.get(parent_key)
                if not parent and props.get("NAME_1"):
                    parent = region_by_name.get(str(props["NAME_1"]).lower())
                if not parent and props.get("Region_Nam"):
                    parent = region_by_name.get(str(props["Region_Nam"]).lower())
                if not parent:
                    lat, lng = _geometry_centroid(geom)
                    for region in region_parents:
                        if point_in_geometry(lng, lat, region.geometry):
                            parent = region
                            break
            elif level == 3:
                parent_key = _parent_lookup_key(props, 3)
                parent = parent_by_code.get(parent_key)
                if not parent and props.get("NAME_2"):
                    parent = parent_by_name.get(str(props["NAME_2"]).lower())
                if not parent and props.get("District_N"):
                    parent = parent_by_name.get(str(props["District_N"]).lower())
            elif level == 4:
                parent_key = _parent_lookup_key(props, 4)
                parent = parent_by_code.get(parent_key)
                if not parent and props.get("NAME_3"):
                    parent = parent_by_name.get(str(props["NAME_3"]).lower())
                if not parent and props.get("Ward_Name"):
                    parent = parent_by_name.get(str(props["Ward_Name"]).lower())

            _upsert_boundary(
                country=country,
                level=level,
                name=name,
                code=code,
                geometry=geom,
                source=source,
                parent=parent,
            )
            count += 1
            if progress_cb and (index % 50 == 0 or index == total):
                progress_cb(index, total)

    if level == 0 and count:
        adm0 = AdminBoundary.objects.filter(country=country, level=0).first()
        if adm0:
            country.boundary = adm0.geometry
            bbox = geometry_bbox(adm0.geometry)
            if bbox:
                min_lat, max_lat, min_lng, max_lng = bbox
                country.bounds = {
                    "west": min_lng,
                    "south": min_lat,
                    "east": max_lng,
                    "north": max_lat,
                }
            country.save(update_fields=["boundary", "bounds"])

    return count


def import_geojson_file(
    country: Country,
    level: int,
    path: Path,
    *,
    source: str = AdminBoundary.Source.GADM,
    replace: bool = False,
) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    features = _features_from_geojson(data)
    return import_features_for_country(country, level, features, source=source, replace=replace)


def build_preset_features(country_code: str, level: int) -> list[dict[str, Any]]:
    code = country_code.upper()
    if level == 0:
        preset = preset_for_code(code)
        boundary = preset.get("boundary")
        if not boundary:
            return []
        return [
            {
                "type": "Feature",
                "properties": {"name": preset.get("name", code), "kind": "country"},
                "geometry": boundary,
            }
        ]
    if level == 1 and code == "TZ":
        features = []
        for name in REGION_CENTERS:
            bounds = region_bounds(name)
            if not bounds:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {"NAME_1": name, "GID_1": _slug_code(name)},
                    "geometry": {"type": "Polygon", "coordinates": [_bbox_ring(bounds)]},
                }
            )
        return features
    return []


def import_country_boundaries(
    country_code: str,
    *,
    levels: list[int] | None = None,
    source: str = AdminBoundary.Source.GADM,
    use_presets_if_missing: bool = True,
) -> dict[int, int]:
    country = Country.objects.get(code=country_code.upper())
    levels = levels if levels is not None else [0, 1, 2]
    results: dict[int, int] = {}
    data_dir = boundaries_data_dir()

    for level in levels:
        path = data_dir / f"{country.code}_adm{level}.json"
        count = 0
        if path.is_file():
            count = import_geojson_file(country, level, path, source=source, replace=True)
        elif use_presets_if_missing:
            features = build_preset_features(country.code, level)
            if features:
                count = import_features_for_country(
                    country,
                    level,
                    features,
                    source=AdminBoundary.Source.PRESET,
                    replace=True,
                )
        results[level] = count
    return results


def boundaries_feature_collection(
    country: Country,
    levels: list[int],
    *,
    uploaded_only: bool = True,
    display: bool = False,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    qs = AdminBoundary.objects.filter(country=country, level__in=levels)
    if uploaded_only:
        qs = qs.filter(source=AdminBoundary.Source.ADMIN_UPLOAD)

    # Sorting by name forces MySQL to materialize/sort large JSON rows (temp disk).
    # Primary-key order is index-friendly for big village layers.
    if levels == [4]:
        qs = qs.order_by("id")
    else:
        qs = qs.order_by("level", "name")

    total = qs.count() if limit is not None else None
    if offset:
        qs = qs[offset:]
    if limit is not None:
        qs = qs[:limit]

    features = []
    chunk = 500 if 4 in levels else 100
    for boundary in qs.iterator(chunk_size=chunk):
        kind = {0: "country", 1: "region", 2: "district", 3: "ward", 4: "village"}.get(
            boundary.level, "admin"
        )
        geometry = boundary.geometry
        if display and boundary.level >= 3:
            geometry = display_geometry(geometry)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": boundary.id,
                    "level": boundary.level,
                    "kind": kind,
                    "name": boundary.name,
                    "name_sw": boundary.name_sw,
                    "code": boundary.code,
                    "region_id": boundary.region_id,
                    "center_lat": boundary.center_lat,
                    "center_lng": boundary.center_lng,
                },
                "geometry": geometry,
            }
        )

    payload: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if total is not None:
        payload["meta"] = {"total": total, "offset": offset, "limit": limit, "count": len(features)}
    return payload


def _boundary_at_point(
    country: Country,
    level: int,
    lat: float,
    lng: float,
    *,
    margin: float | None = None,
) -> dict[str, Any] | None:
    if margin is None:
        margin = 0.06 if level == 4 else 0.45
    qs = AdminBoundary.objects.filter(
        country=country,
        level=level,
        source=AdminBoundary.Source.ADMIN_UPLOAD,
        center_lat__gte=lat - margin,
        center_lat__lte=lat + margin,
        center_lng__gte=lng - margin,
        center_lng__lte=lng + margin,
    ).only("id", "name", "name_sw", "code", "level", "geometry", "center_lat", "center_lng", "region_id")
    for boundary in qs:
        if point_in_geometry(lng, lat, boundary.geometry):
            return _boundary_payload(boundary)
    return None


def lookup_boundaries_at_point(
    country: Country,
    lat: float,
    lng: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {"region": None, "district": None, "ward": None, "village": None}

    result["village"] = _boundary_at_point(country, 4, lat, lng)
    result["ward"] = _boundary_at_point(country, 3, lat, lng)
    result["district"] = _boundary_at_point(country, 2, lat, lng)
    result["region"] = _boundary_at_point(country, 1, lat, lng)

    return result


def _boundary_payload(boundary: AdminBoundary) -> dict[str, Any]:
    bbox = geometry_bbox(boundary.geometry)
    bounds = None
    if bbox:
        min_lat, max_lat, min_lng, max_lng = bbox
        bounds = {"west": min_lng, "south": min_lat, "east": max_lng, "north": max_lat}
    return {
        "id": boundary.id,
        "level": boundary.level,
        "name": boundary.name,
        "name_sw": boundary.name_sw,
        "code": boundary.code,
        "region_id": boundary.region_id,
        "center": {"lat": boundary.center_lat, "lng": boundary.center_lng},
        "bounds": bounds,
    }


def country_level0_geometry(country: Country) -> dict[str, Any] | None:
    adm0 = AdminBoundary.objects.filter(
        country=country, level=0, source=AdminBoundary.Source.ADMIN_UPLOAD
    ).first()
    if adm0:
        return adm0.geometry
    if country.boundary:
        return country.boundary
    preset = preset_for_code(country.code)
    return preset.get("boundary")


@transaction.atomic
def import_uploaded_boundaries(
    country_code: str,
    level: int,
    features: list[dict[str, Any]],
    *,
    replace: bool = True,
    progress_cb: Callable[[int, int], None] | None = None,
) -> int:
    country = Country.objects.get(code=country_code.upper())
    if replace:
        AdminBoundary.objects.filter(country=country, level=level).delete()
    return import_features_for_country(
        country,
        level,
        features,
        source=AdminBoundary.Source.ADMIN_UPLOAD,
        replace=False,
        progress_cb=progress_cb,
    )
