"""Map analysis area limits: 10 km² default zone, paid km² extension around the click."""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_UP

from django.conf import settings

from apps.maps.access import user_has_map_detail_access

from .map_view_area import analysis_zone_deltas_degrees, included_analysis_km2


def included_aerial_km2() -> float:
    return included_analysis_km2()


def max_analysis_km2() -> float:
    return float(getattr(settings, "AERIAL_MAX_ANALYSIS_KM2", 300))


def max_billable_extra_km2() -> float:
    configured = float(getattr(settings, "AERIAL_MAX_BILLABLE_EXTRA_KM2", 290))
    ceiling = max(0.0, max_analysis_km2() - included_aerial_km2())
    return min(configured, ceiling)


def clamp_analysis_km2(area_km2: float | None) -> float:
    """Keep analysis zones within the platform maximum."""
    if area_km2 is None or area_km2 <= 0:
        return included_aerial_km2()
    return min(float(area_km2), max_analysis_km2())


def aerial_price_per_km2() -> Decimal:
    return Decimal(str(getattr(settings, "AERIAL_PRICE_PER_KM2", 10000)))


def extension_price(extra_km2: float) -> Decimal:
    if extra_km2 <= 0:
        return Decimal("0")
    billable = int(math.ceil(extra_km2))
    return (aerial_price_per_km2() * billable).quantize(Decimal("1"), rounding=ROUND_UP)


def find_active_grant(user, lat: float, lng: float):
    from .models import AerialAnalysisGrant

    for grant in AerialAnalysisGrant.objects.filter(user=user, is_active=True).order_by("-created_at"):
        if grant.covers_click(lat, lng):
            return grant
    return None


def staff_unlimited_aerial_zone(user) -> bool:
    """Platform staff get the max analysis zone without per-click payment."""
    if user is None or not user.is_authenticated:
        return False
    return bool(getattr(user, "is_admin_user", False) or getattr(user, "is_mineral_manager", False))


def staff_analysis_km2() -> float:
    return max_analysis_km2()


def user_can_access_aerial_analysis(
    user,
    lat: float,
    lng: float,
    zoom: int,
    **_kwargs,
) -> dict:
    """Default 10 km² around click; paid grants widen the zone at that location."""
    default_km2 = included_aerial_km2()
    staff_zone = staff_unlimited_aerial_zone(user)
    grant = None if staff_zone else (find_active_grant(user, lat, lng) if user.is_authenticated else None)

    if staff_zone:
        effective_km2 = staff_analysis_km2()
        purchased_extra = max(0.0, effective_km2 - default_km2)
        using_extended = effective_km2 > default_km2
    elif grant:
        effective_km2 = clamp_analysis_km2(float(grant.max_area_km2))
        purchased_extra = float(grant.purchased_extra_km2)
        using_extended = effective_km2 > default_km2
    else:
        effective_km2 = default_km2
        purchased_extra = 0.0
        using_extended = False

    lat_delta, lng_delta = analysis_zone_deltas_degrees(lat, effective_km2)

    result = {
        "default_analysis_km2": default_km2,
        "analysis_area_km2": round(effective_km2, 2),
        "max_analysis_km2": max_analysis_km2(),
        "included_km2": default_km2,
        "purchased_extra_km2": round(purchased_extra, 2),
        "using_extended_area": using_extended,
        "allowed": True,
        "requires_extension_purchase": False,
        "requires_aerial_purchase": False,
        "requires_zoom_in": False,
        "extension_available": False,
        "aerial_price_per_km2": float(aerial_price_per_km2()),
        "aerial_total_price": 0,
        "zone_center": {"lat": lat, "lng": lng},
        "zone_bounds": {
            "south": lat - lat_delta,
            "north": lat + lat_delta,
            "west": lng - lng_delta,
            "east": lng + lng_delta,
        },
    }

    if not user_has_map_detail_access(user):
        result["allowed"] = False
        result["requires_subscription"] = True
        return result

    if not using_extended and not staff_zone:
        result["extension_available"] = True
        result["extension_options_km2"] = [
            km2 for km2 in (10, 25, 50, 100) if km2 <= max_billable_extra_km2()
        ]

    if staff_zone:
        result["staff_unlimited_zone"] = True

    return result
