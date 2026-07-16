"""Mineral exploration quotas by subscription package."""

from __future__ import annotations

from apps.accounts.models import User
from apps.reports.access import _active_paid_subscription
from apps.subscriptions.models import SubscriptionPlan

from .credits import _month_period_bounds

FREE_MINERAL_EXPLORATION_LIMIT = 0
DEFAULT_STARTER_MINERAL_LIMIT = 5
DEFAULT_GROWTH_MINERAL_LIMIT = 10


class MineralExplorationLimitExceeded(Exception):
    def __init__(self, quota: dict, slug: str):
        self.quota = quota
        self.slug = slug
        super().__init__("Mineral exploration limit reached for your plan.")


def plan_mineral_exploration_limit(plan) -> int | None:
    """Return max unique minerals per period; ``None`` means unlimited (11+)."""
    if plan.max_explorable_minerals is None:
        return None
    return int(plan.max_explorable_minerals)


def _explored_slugs_for_user(user, *, period_start) -> list[str]:
    from .models import MineralExplorationLog

    if not user or not user.is_authenticated:
        return []
    return list(
        MineralExplorationLog.objects.filter(
            user=user,
            created_at__date__gte=period_start,
        )
        .order_by("mineral_slug")
        .values_list("mineral_slug", flat=True)
        .distinct()
    )


def get_mineral_exploration_quota(request, user=None) -> dict:
    user = user if user is not None else getattr(request, "user", None)
    start, end = _month_period_bounds()

    if user and user.is_authenticated:
        if user.is_admin_user or user.role == User.Role.MINERAL_MANAGER:
            return {
                "limit": None,
                "used": 0,
                "remaining": None,
                "explored_slugs": [],
                "period_end": end.isoformat(),
                "period_label": "monthly",
                "tier": "unlimited",
                "unlimited": True,
            }

        sub = _active_paid_subscription(user)
        explored = _explored_slugs_for_user(user, period_start=start)
        used = len(explored)

        if sub:
            limit = plan_mineral_exploration_limit(sub.plan)
            if limit is None:
                return {
                    "limit": None,
                    "used": used,
                    "remaining": None,
                    "explored_slugs": explored,
                    "period_end": end.isoformat(),
                    "period_label": "monthly",
                    "tier": "premium",
                    "unlimited": True,
                }
            remaining = max(0, limit - used)
            tier = "starter" if limit <= DEFAULT_STARTER_MINERAL_LIMIT else "growth"
            return {
                "limit": limit,
                "used": used,
                "remaining": remaining,
                "explored_slugs": explored,
                "period_end": end.isoformat(),
                "period_label": "monthly",
                "tier": tier,
                "unlimited": False,
            }

        limit = FREE_MINERAL_EXPLORATION_LIMIT
        return {
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used),
            "explored_slugs": explored,
            "period_end": end.isoformat(),
            "period_label": "monthly",
            "tier": "free",
            "unlimited": False,
        }

    return {
        "limit": FREE_MINERAL_EXPLORATION_LIMIT,
        "used": 0,
        "remaining": FREE_MINERAL_EXPLORATION_LIMIT,
        "explored_slugs": [],
        "period_end": end.isoformat(),
        "period_label": "monthly",
        "tier": "anonymous",
        "unlimited": False,
    }


def can_explore_mineral(quota: dict, slug: str) -> bool:
    slug = (slug or "").strip()
    if not slug:
        return False
    if quota.get("unlimited"):
        return True
    if slug in (quota.get("explored_slugs") or []):
        return True
    remaining = quota.get("remaining")
    if remaining is None:
        return quota.get("limit") is None
    return remaining > 0


def user_can_view_mineral_heatmap(user, quota: dict, slug: str) -> bool:
    """Concentration heatmaps: Plus/Pro (and staff), and they consume explore quota."""
    slug = (slug or "").strip()
    if not slug:
        return False
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_admin_user", False):
        return True
    if getattr(user, "role", None) == User.Role.MINERAL_MANAGER:
        return True
    # Starter / Explorer: show-on-map yes; concentration overlays are Plus/Pro only.
    if not getattr(user, "can_use_analytics", False):
        return False
    return can_explore_mineral(quota, slug)


def record_mineral_exploration(user, slug: str) -> None:
    from .models import MineralExplorationLog

    slug = (slug or "").strip()
    if not user or not user.is_authenticated or not slug:
        return

    start, _ = _month_period_bounds()
    if MineralExplorationLog.objects.filter(
        user=user,
        mineral_slug=slug,
        created_at__date__gte=start,
    ).exists():
        return

    sub = _active_paid_subscription(user)
    MineralExplorationLog.objects.create(
        user=user,
        mineral_slug=slug,
        subscription=sub,
    )


def ensure_mineral_exploration_allowed(request, slug: str, *, user=None) -> dict:
    user = user if user is not None else getattr(request, "user", None)
    quota = get_mineral_exploration_quota(request, user=user)
    if not can_explore_mineral(quota, slug):
        raise MineralExplorationLimitExceeded(quota, slug)
    if user and user.is_authenticated:
        record_mineral_exploration(user, slug)
        quota = get_mineral_exploration_quota(request, user=user)
    return quota
