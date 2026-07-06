"""Background admin boundary import with cache-backed progress."""

from __future__ import annotations

import threading
import uuid
from typing import Any

from django.core.cache import cache

from apps.maps.shapefile_utils import parse_upload_content
from apps.maps.upload_security import check_disk_headroom, friendly_upload_error

from .admin_boundary_service import import_uploaded_boundaries

CACHE_PREFIX = "boundary_import:"
CACHE_TTL = 7200


def _cache_key(task_id: str) -> str:
    return f"{CACHE_PREFIX}{task_id}"


def get_import_status(task_id: str) -> dict[str, Any] | None:
    return cache.get(_cache_key(task_id))


def _set_status(task_id: str, payload: dict[str, Any]) -> None:
    cache.set(_cache_key(task_id), payload, CACHE_TTL)


def _features_from_parsed(features_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for feat in features_data:
        if isinstance(feat, dict) and feat.get("geometry"):
            features.append(feat)
    if not features and features_data:
        features = [
            {
                "type": "Feature",
                "properties": f.get("properties", {}),
                "geometry": f.get("geometry"),
            }
            for f in features_data
            if f.get("geometry")
        ]
    return features


def _run_import(
    task_id: str,
    country_code: str,
    level: int,
    content: bytes,
    filename: str,
    replace: bool,
) -> None:
    try:
        _set_status(
            task_id,
            {"status": "processing", "phase": "parsing", "done": 0, "total": 0},
        )
        check_disk_headroom(boundary=True)
        features_data = parse_upload_content(content, filename, boundary=True)
        features = _features_from_parsed(features_data)
        if not features:
            _set_status(task_id, {"status": "failed", "error": "No features found in upload."})
            return

        total = len(features)

        def progress(done: int, feature_total: int) -> None:
            if done % 50 != 0 and done != feature_total:
                return
            _set_status(
                task_id,
                {
                    "status": "processing",
                    "phase": "importing",
                    "done": done,
                    "total": feature_total,
                },
            )

        _set_status(
            task_id,
            {"status": "processing", "phase": "importing", "done": 0, "total": total},
        )
        check_disk_headroom(boundary=True)
        count = import_uploaded_boundaries(
            country_code,
            level,
            features,
            replace=replace,
            progress_cb=progress,
        )
        _set_status(
            task_id,
            {
                "status": "completed",
                "imported": count,
                "country": country_code,
                "level": level,
                "total": total,
            },
        )
        if level == 4 and count:
            from .models import Country

            from .boundary_map_cache import build_village_display_cache, invalidate_village_display_cache

            country = Country.objects.filter(code=country_code).first()
            if country:
                invalidate_village_display_cache(country_code)
                try:
                    build_village_display_cache(country)
                except Exception:
                    pass
    except Exception as exc:
        _set_status(
            task_id,
            {
                "status": "failed",
                "error": friendly_upload_error(exc),
            },
        )


def start_boundary_import(
    country_code: str,
    level: int,
    content: bytes,
    filename: str,
    *,
    replace: bool = True,
) -> str:
    task_id = str(uuid.uuid4())
    _set_status(
        task_id,
        {"status": "processing", "phase": "starting", "done": 0, "total": 0},
    )
    thread = threading.Thread(
        target=_run_import,
        args=(task_id, country_code, level, content, filename, replace),
        daemon=True,
    )
    thread.start()
    return task_id
