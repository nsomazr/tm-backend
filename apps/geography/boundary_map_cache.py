"""On-disk cache for large village boundary map layers (avoids heavy MySQL reads)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterator

from django.conf import settings

from .admin_boundary_service import display_geometry
from .models import AdminBoundary, Country

CACHE_DIR = Path(settings.BASE_DIR) / "data" / "boundary_cache"


def village_cache_path(country_code: str) -> Path:
    return CACHE_DIR / f"{country_code.upper()}_villages_display.json.gz"


def village_cache_meta_path(country_code: str) -> Path:
    return CACHE_DIR / f"{country_code.upper()}_villages_display.meta.json"


def _iter_village_rows(country: Country, batch_size: int = 100) -> Iterator[AdminBoundary]:
    last_id = 0
    while True:
        rows = list(
            AdminBoundary.objects.filter(
                country=country,
                level=AdminBoundary.Level.VILLAGE,
                source=AdminBoundary.Source.ADMIN_UPLOAD,
                id__gt=last_id,
            )
            .order_by("id")
            .only(
                "id",
                "level",
                "name",
                "name_sw",
                "code",
                "region_id",
                "center_lat",
                "center_lng",
                "geometry",
            )[:batch_size]
        )
        if not rows:
            break
        yield from rows
        last_id = rows[-1].id


def _boundary_to_feature(boundary: AdminBoundary, *, display: bool) -> dict[str, Any]:
    geometry = boundary.geometry
    if display:
        geometry = display_geometry(geometry)
    return {
        "type": "Feature",
        "properties": {
            "id": boundary.id,
            "level": boundary.level,
            "kind": "village",
            "name": boundary.name,
            "name_sw": boundary.name_sw,
            "code": boundary.code,
            "region_id": boundary.region_id,
            "center_lat": boundary.center_lat,
            "center_lng": boundary.center_lng,
        },
        "geometry": geometry,
    }


def build_village_display_cache(country: Country) -> int:
    """Build gzip GeoJSON cache; returns feature count."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = village_cache_path(country.code)
    count = 0

    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write('{"type":"FeatureCollection","features":[')
        first = True
        for boundary in _iter_village_rows(country):
            if not first:
                handle.write(",")
            json.dump(_boundary_to_feature(boundary, display=True), handle, separators=(",", ":"))
            first = False
            count += 1
        handle.write("]}")

    village_cache_meta_path(country.code).write_text(
        json.dumps({"country": country.code, "count": count, "display": True}),
        encoding="utf-8",
    )
    return count


def load_village_display_cache(
    country_code: str,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any] | None:
    path = village_cache_path(country_code)
    if not path.is_file():
        return None

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)

    features = data.get("features") or []
    total = len(features)
    if offset:
        features = features[offset:]
    if limit is not None:
        features = features[:limit]

    payload: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if limit is not None:
        payload["meta"] = {
            "total": total,
            "offset": offset,
            "limit": limit,
            "count": len(features),
            "cached": True,
        }
    return payload


def invalidate_village_display_cache(country_code: str) -> None:
    for path in (village_cache_path(country_code), village_cache_meta_path(country_code)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
