"""Map layer access rules for list/geojson/insights."""

from django.conf import settings
from django.db.models import Count, Q

from apps.accounts.models import User


def user_has_map_detail_access(user) -> bool:
    if user is None or not user.is_authenticated:
        return False
    if user.has_paid_access or user.is_admin_user:
        return True
    return user.role == User.Role.MINERAL_MANAGER


def preview_coord_decimals() -> int:
    """Decimal places of coordinate precision served to non-paying users.

    Fewer decimals => coarser location (2 ≈ 1.1 km, 3 ≈ 110 m, 4 ≈ 11 m). This
    keeps the free map a usable teaser while making exact dig coordinates
    unusable for bulk scraping. Configurable via MAP_PREVIEW_COORD_DECIMALS
    (default 3 so small claim polygons still render).
    """
    return int(getattr(settings, "MAP_PREVIEW_COORD_DECIMALS", 3))


def _round_coords(coords, ndigits):
    if isinstance(coords, (int, float)):
        return round(coords, ndigits)
    if isinstance(coords, (list, tuple)):
        return [_round_coords(c, ndigits) for c in coords]
    return coords


def coarsen_geometry(geometry, ndigits=None):
    """Return a copy of a GeoJSON geometry with coordinates rounded to ``ndigits``.

    Used to degrade precision for anonymous/free users so the crown-jewel exact
    coordinates never leave the server at full resolution.
    """
    if not isinstance(geometry, dict):
        return geometry
    if ndigits is None:
        ndigits = preview_coord_decimals()
    if geometry.get("type") == "GeometryCollection":
        return {
            **geometry,
            "geometries": [coarsen_geometry(g, ndigits) for g in geometry.get("geometries", [])],
        }
    coords = geometry.get("coordinates")
    if coords is None:
        return geometry
    return {**geometry, "coordinates": _round_coords(coords, ndigits)}


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
    """Scope layers for the current viewer.

    - Mineral managers (without admin) see only assigned minerals.
    - Free / anonymous users only see layers marked ``is_preview`` (free map + legend).
    - Paid users and admins see all active mapped layers.
    """
    if user is not None and user.is_authenticated and user.role == User.Role.MINERAL_MANAGER and not user.is_admin_user:
        if not user.has_paid_access:
            managed_ids = list(user.mineral_assignments.values_list("mineral_id", flat=True))
            if managed_ids:
                return queryset.filter(mineral_id__in=managed_ids)
    if not user_has_map_detail_access(user):
        return queryset.filter(is_preview=True)
    return queryset
