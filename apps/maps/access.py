"""Map layer access rules for list/geojson/insights."""

from django.db.models import Count, Q

from apps.accounts.models import User


def user_has_map_detail_access(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.has_paid_access or user.is_admin_user:
        return True
    return user.role == User.Role.MINERAL_MANAGER


def layers_with_mapped_data(queryset):
    """Only layers that have at least one active feature (uploaded geometry)."""
    return queryset.annotate(
        active_feature_count=Count("features", filter=Q(features__is_active=True))
    ).filter(active_feature_count__gt=0)


MAPPED_LAYER_COUNT_FILTER = Q(
    layers__is_active=True,
    layers__features__is_active=True,
)


def filter_layers_for_user(queryset, user):
    """All users see active map geometry; mineral managers are scoped to assigned minerals."""
    if user is not None and user.is_authenticated and user.role == User.Role.MINERAL_MANAGER and not user.is_admin_user:
        if not user.has_paid_access:
            managed_ids = list(user.mineral_assignments.values_list("mineral_id", flat=True))
            if managed_ids:
                return queryset.filter(mineral_id__in=managed_ids)
    return queryset
