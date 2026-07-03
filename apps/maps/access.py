"""Map layer access rules for list/geojson/insights."""

from apps.accounts.models import User


def user_has_map_detail_access(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.has_paid_access or user.is_admin_user:
        return True
    return user.role == User.Role.MINERAL_MANAGER


def filter_layers_for_user(queryset, user):
    """All users see active map geometry; mineral managers are scoped to assigned minerals."""
    if user.is_authenticated and user.role == User.Role.MINERAL_MANAGER and not user.is_admin_user:
        if not user.has_paid_access:
            managed_ids = list(user.mineral_assignments.values_list("mineral_id", flat=True))
            if managed_ids:
                return queryset.filter(mineral_id__in=managed_ids)
    return queryset
