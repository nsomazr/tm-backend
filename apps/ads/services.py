from __future__ import annotations

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.accounts.models import User

from .models import Ad, AdAudience, AdEvent, AdPlacement


def _user_audience(user) -> str:
    if not user or not getattr(user, "is_authenticated", False):
        return AdAudience.FREE
    role = getattr(user, "role", "")
    if role in (User.Role.SUBSCRIBER, User.Role.MINERAL_MANAGER, User.Role.ADMIN, User.Role.SUPER_ADMIN):
        return AdAudience.SUBSCRIBER
    return AdAudience.FREE


def _matches_audience(ad: Ad, audience: str) -> bool:
    if ad.audience == AdAudience.ALL:
        return True
    return ad.audience == audience


def _matches_country(ad: Ad, country_code: str | None) -> bool:
    codes = ad.country_codes or []
    if not codes:
        return True
    if not country_code:
        return True
    return country_code.upper() in {code.upper() for code in codes}


def active_ads(*, now=None) -> list[Ad]:
    now = now or timezone.now()
    qs = Ad.objects.filter(is_active=True, is_hidden=False)
    live: list[Ad] = []
    for ad in qs.order_by("-priority", "-created_at"):
        if ad.is_live(now=now):
            live.append(ad)
    return live


_PLACEMENT_GROUPS: dict[str, set[str]] = {
    AdPlacement.MAP_OVERLAY: {AdPlacement.MAP_OVERLAY, AdPlacement.MAP_SIDEBAR},
}


def _placement_codes_for(placement: str) -> set[str]:
    return _PLACEMENT_GROUPS.get(placement, {placement})


def ads_for_placement(
    placement: str,
    *,
    user=None,
    country_code: str | None = "TZ",
    limit: int = 3,
) -> list[Ad]:
    if placement not in AdPlacement.values:
        return []
    target_placements = _placement_codes_for(placement)
    audience = _user_audience(user)
    matched: list[Ad] = []
    for ad in active_ads():
        placements = ad.placements or []
        if not target_placements.intersection(placements):
            continue
        if not _matches_audience(ad, audience):
            continue
        if not _matches_country(ad, country_code):
            continue
        matched.append(ad)
        if len(matched) >= limit:
            break
    return matched


def record_ad_event(
    ad: Ad,
    *,
    kind: str,
    placement: str,
    user=None,
    session_key: str = "",
) -> AdEvent:
    event = AdEvent.objects.create(
        ad=ad,
        kind=kind,
        placement=placement,
        user=user if user and getattr(user, "is_authenticated", False) else None,
        session_key=(session_key or "")[:64],
    )
    if kind == AdEvent.Kind.IMPRESSION:
        Ad.objects.filter(pk=ad.pk).update(impression_count=F("impression_count") + 1)
        ad.impression_count += 1
    elif kind == AdEvent.Kind.CLICK:
        Ad.objects.filter(pk=ad.pk).update(click_count=F("click_count") + 1)
        ad.click_count += 1
    return event


def build_ad_admin_stats() -> dict:
    now = timezone.now()
    live_q = Q(is_active=True, is_hidden=False) & (
        Q(starts_at__isnull=True) | Q(starts_at__lte=now)
    ) & (Q(ends_at__isnull=True) | Q(ends_at__gte=now))
    totals = Ad.objects.aggregate(
        campaigns=Count("id"),
        live=Count("id", filter=live_q),
        impressions=Sum("impression_count"),
        clicks=Sum("click_count"),
    )
    impressions = int(totals.get("impressions") or 0)
    clicks = int(totals.get("clicks") or 0)
    ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
    by_placement = []
    for placement, label in AdPlacement.choices:
        rows = (
            AdEvent.objects.filter(placement=placement)
            .values("kind")
            .annotate(total=Count("id"))
        )
        counts = {row["kind"]: row["total"] for row in rows}
        imp = int(counts.get(AdEvent.Kind.IMPRESSION, 0))
        clk = int(counts.get(AdEvent.Kind.CLICK, 0))
        by_placement.append(
            {
                "placement": placement,
                "label": label,
                "impressions": imp,
                "clicks": clk,
                "ctr": round((clk / imp) * 100, 2) if imp else 0.0,
            }
        )
    return {
        "campaigns": int(totals.get("campaigns") or 0),
        "live_campaigns": int(totals.get("live") or 0),
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "reach": impressions,
        "by_placement": by_placement,
    }
