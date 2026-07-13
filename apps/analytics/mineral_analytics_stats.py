from django.db.models import Count, Q
from django.utils import timezone

from apps.minerals.models import Mineral

from .admin_stats import ADMIN_HOTSPOT_FEATURE_CAP
from .coverage_stats import (
    ANALYTICS_LAYER_TYPES,
    analytics_features_qs,
    analytics_layers_qs,
    build_hotspots_by_region,
    build_layer_inventory,
)
from .mineral_coverage import mineral_catalog_stats
from .models import MineralExplorationLog


def build_admin_mineral_analytics() -> dict:
    now = timezone.now()

    active_features = analytics_features_qs()
    total_features = active_features.count()
    analytics_layers = analytics_layers_qs()
    total_layers = analytics_layers.count()
    preview_layers = analytics_layers.filter(is_preview=True).count()

    layer_by_type = list(
        analytics_layers.values("layer_type").annotate(count=Count("id"))
    )
    hotspots_by_region = build_hotspots_by_region(
        active_features,
        max_features=ADMIN_HOTSPOT_FEATURE_CAP,
    )
    layers_inventory = build_layer_inventory()
    regions_covered = len([row for row in hotspots_by_region if row["region"] != "Unknown"])

    mineral_layer_filter = Q(
        layers__is_active=True,
        layers__layer_type__in=ANALYTICS_LAYER_TYPES,
        layers__features__is_active=True,
    )
    minerals = list(
        Mineral.objects.filter(is_active=True)
        .annotate(
            layer_count=Count(
                "layers",
                filter=mineral_layer_filter,
                distinct=True,
            ),
            feature_count=Count(
                "layers__features",
                filter=mineral_layer_filter,
                distinct=True,
            ),
            report_count=Count("reports", filter=Q(reports__is_active=True), distinct=True),
        )
        .values("name", "slug", "color", "layer_count", "feature_count", "report_count")
        .order_by("-feature_count")
    )

    exploration_interest = list(
        MineralExplorationLog.objects.values("mineral_slug")
        .annotate(
            explorations=Count("id"),
            unique_users=Count("user", distinct=True),
        )
        .order_by("-explorations")[:15]
    )

    catalog = mineral_catalog_stats()

    return {
        "generated_at": now.isoformat(),
        "catalog": catalog,
        "coverage": {
            "total_prospects": total_features,
            "total_layers": total_layers,
            "preview_layers": preview_layers,
            "regions_covered": regions_covered,
            "layer_by_type": layer_by_type,
            "hotspots_by_region": hotspots_by_region,
            "layers": layers_inventory,
            "minerals": minerals,
        },
        "exploration_interest": exploration_interest,
    }
