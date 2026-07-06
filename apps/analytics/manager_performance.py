"""Admin review of mineral manager contributions and activity."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import User
from apps.maps.models import LayerUpload, LayerVersion, MapFeature, MapLayer
from apps.reports.models import Report


def _classify_geometry(gtype: str) -> str:
    if gtype in ("Point", "MultiPoint"):
        return "points"
    if gtype in ("LineString", "MultiLineString"):
        return "lines"
    if gtype in ("Polygon", "MultiPolygon"):
        return "polygons"
    return "other"


def _feature_counts(features_qs) -> dict[str, int]:
    counts = {"points": 0, "lines": 0, "polygons": 0, "other": 0}
    for geometry in features_qs.values_list("geometry", flat=True):
        bucket = _classify_geometry((geometry or {}).get("type", ""))
        counts[bucket] = counts.get(bucket, 0) + 1
    counts["total"] = sum(counts.values())
    return counts


def build_manager_performance_review() -> dict:
    since_30d = timezone.now() - timedelta(days=30)
    managers = (
        User.objects.filter(role=User.Role.MINERAL_MANAGER)
        .prefetch_related("mineral_assignments__mineral")
        .order_by("username")
    )

    rows: list[dict] = []
    for manager in managers:
        assignments = list(manager.mineral_assignments.select_related("mineral"))
        mineral_ids = [a.mineral_id for a in assignments]
        minerals = [a.mineral for a in assignments]
        layer_ids = list(
            MapLayer.objects.filter(mineral_id__in=mineral_ids).values_list("id", flat=True)
        )

        personal_qs = MapFeature.objects.filter(created_by=manager, is_active=True)
        personal_counts = _feature_counts(personal_qs)
        personal_counts["recent_30d"] = personal_qs.filter(created_at__gte=since_30d).count()

        scope_qs = MapFeature.objects.filter(layer_id__in=layer_ids, is_active=True)
        scope_counts = _feature_counts(scope_qs)

        uploads = LayerUpload.objects.filter(uploaded_by=manager)
        upload_stats = {
            "total": uploads.count(),
            "completed": uploads.filter(status=LayerUpload.Status.COMPLETED).count(),
            "failed": uploads.filter(status=LayerUpload.Status.FAILED).count(),
            "pending": uploads.filter(
                status__in=[LayerUpload.Status.PENDING, LayerUpload.Status.PROCESSING]
            ).count(),
            "recent_30d": uploads.filter(created_at__gte=since_30d).count(),
        }

        versions_count = LayerVersion.objects.filter(uploaded_by=manager).count()
        layers_created = MapLayer.objects.filter(created_by=manager).count()
        reports_published = Report.objects.filter(created_by=manager, is_active=True).count()

        last_feature = personal_qs.aggregate(t=Max("created_at"))["t"]
        last_upload = uploads.aggregate(t=Max("created_at"))["t"]
        last_report = Report.objects.filter(created_by=manager).aggregate(t=Max("updated_at"))["t"]
        candidates = [t for t in (last_feature, last_upload, last_report) if t]
        last_activity = max(candidates) if candidates else None

        can_publish = any(a.can_publish for a in assignments)

        contribution_score = (
            personal_counts["points"]
            + personal_counts["lines"] * 2
            + personal_counts["polygons"] * 3
            + upload_stats["completed"] * 5
            + layers_created * 10
            + reports_published * 8
        )

        rows.append(
            {
                "user_id": manager.id,
                "username": manager.username,
                "full_name": manager.get_full_name() or "",
                "email": manager.email,
                "is_active": manager.is_active,
                "assigned_minerals": len(mineral_ids),
                "mineral_names": [m.name for m in minerals],
                "can_publish": can_publish,
                "layers_managed": len(layer_ids),
                "layers_created": layers_created,
                "reports_published": reports_published,
                "features": {
                    **personal_counts,
                    "on_managed_layers": scope_counts["total"],
                    "on_managed_layers_breakdown": {
                        "points": scope_counts["points"],
                        "lines": scope_counts["lines"],
                        "polygons": scope_counts["polygons"],
                    },
                },
                "uploads": upload_stats,
                "versions": versions_count,
                "last_activity": last_activity.isoformat() if last_activity else None,
                "contribution_score": contribution_score,
            }
        )

    rows.sort(
        key=lambda row: (
            row["contribution_score"],
            row["features"]["total"],
            row["uploads"]["completed"],
        ),
        reverse=True,
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    return {
        "managers": rows,
        "generated_at": timezone.now().isoformat(),
    }
