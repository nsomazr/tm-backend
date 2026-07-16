from apps.accounts.models import User


def get_managed_mineral_ids(user):
    if not user.is_authenticated:
        return []
    if user.role in (User.Role.SUPER_ADMIN, User.Role.ADMIN):
        return None
    if user.role == User.Role.MINERAL_MANAGER:
        return list(
            user.mineral_assignments.values_list("mineral_id", flat=True)
        )
    return []


def user_can_manage_mineral(user, mineral_id):
    if not user.is_authenticated:
        return False
    if user.role in (User.Role.SUPER_ADMIN, User.Role.ADMIN):
        return True
    if user.role == User.Role.MINERAL_MANAGER:
        return user.mineral_assignments.filter(mineral_id=mineral_id).exists()
    return False


def user_is_mineral_manager_only(user) -> bool:
    """True for mineral managers (not platform admins)."""
    return (
        bool(user)
        and getattr(user, "is_authenticated", False)
        and getattr(user, "role", None) == User.Role.MINERAL_MANAGER
    )


def assert_manager_point_layer_access(user, *, layer_type: str | None = None, layer=None) -> None:
    """Mineral managers may only create/edit/upload point (occurrence) layers."""
    if not user_is_mineral_manager_only(user):
        return
    from rest_framework.exceptions import PermissionDenied

    from apps.maps.models import MapLayer

    resolved = layer_type
    if resolved is None and layer is not None:
        resolved = getattr(layer, "layer_type", None)
    if resolved != MapLayer.LayerType.POINT:
        raise PermissionDenied(
            "Mineral managers may only work with point (occurrence) layers. "
            "Polygons, lines, and other map tools are limited to platform admins."
        )
