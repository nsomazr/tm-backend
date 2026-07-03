"""Ask Terra assistant credit quotas and consumption."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.reports.access import _active_paid_subscription
from apps.subscriptions.models import SubscriptionPlan

from .chat_history import user_has_chat_history

FREE_MONTHLY_CREDITS = 500
ANONYMOUS_SESSION_CREDITS = 5
DEFAULT_MONTHLY_PLAN_CREDITS = 3000
DEFAULT_ANNUAL_PLAN_CREDITS = 5000


class InsufficientAssistantCredits(Exception):
    def __init__(self, quota: dict):
        self.quota = quota
        super().__init__("Insufficient assistant credits")


def plan_assistant_credit_limit(plan) -> int:
    if plan.included_assistant_credits:
        return plan.included_assistant_credits
    if plan.billing_cycle == SubscriptionPlan.BillingCycle.ANNUAL:
        return DEFAULT_ANNUAL_PLAN_CREDITS
    return DEFAULT_MONTHLY_PLAN_CREDITS


def _month_period_bounds(day: date | None = None) -> tuple[date, date]:
    day = day or timezone.now().date()
    start = day.replace(day=1)
    last = monthrange(day.year, day.month)[1]
    end = day.replace(day=last)
    return start, end


def _session_key(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key or ""


def _usage_queryset(*, user=None, session_key="", period_start=None, subscription=None):
    from .models import AssistantCreditUsage

    if subscription:
        return AssistantCreditUsage.objects.filter(subscription=subscription)
    if user and user.is_authenticated:
        qs = AssistantCreditUsage.objects.filter(user=user, subscription__isnull=True)
        if period_start:
            qs = qs.filter(created_at__date__gte=period_start)
        return qs
    if session_key:
        return AssistantCreditUsage.objects.filter(session_key=session_key, user__isnull=True)
    return AssistantCreditUsage.objects.none()


def _used_credits(qs) -> int:
    return qs.aggregate(total=Sum("credits"))["total"] or 0


def _paid_credit_usage(sub):
    """Paid plans refresh Ask Terra credits every calendar month."""
    start, end = _month_period_bounds()
    return _usage_queryset(subscription=sub).filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
    )


def _quota_with_history(user, base: dict) -> dict:
    base["chat_history"] = user_has_chat_history(user) if user and user.is_authenticated else False
    return base


def get_assistant_credit_quota(request, user=None) -> dict:
    user = user if user is not None else getattr(request, "user", None)

    if user and user.is_authenticated:
        if user.is_admin_user or user.role == User.Role.MINERAL_MANAGER:
            return _quota_with_history(
                user,
                {
                "limit": None,
                "used": 0,
                "remaining": None,
                "period_end": None,
                "period_label": None,
                "tier": "unlimited",
                "unlimited": True,
            },
            )

        sub = _active_paid_subscription(user)
        if sub:
            limit = plan_assistant_credit_limit(sub.plan)
            used = _used_credits(_paid_credit_usage(sub))
            remaining = max(0, limit - used)
            _, period_end = _month_period_bounds()
            return _quota_with_history(
                user,
                {
                "limit": limit,
                "used": used,
                "remaining": remaining,
                "period_end": period_end.isoformat(),
                "period_label": "monthly",
                "tier": "paid",
                "unlimited": False,
            },
            )

        start, end = _month_period_bounds()
        limit = FREE_MONTHLY_CREDITS
        used = _used_credits(_usage_queryset(user=user, period_start=start))
        remaining = max(0, limit - used)
        return _quota_with_history(
            user,
            {
            "limit": limit,
            "used": used,
            "remaining": remaining,
            "period_end": end.isoformat(),
            "period_label": "monthly",
            "tier": "free",
            "unlimited": False,
        },
        )

    session_key = _session_key(request) if request else ""
    limit = ANONYMOUS_SESSION_CREDITS
    used = _used_credits(_usage_queryset(session_key=session_key))
    remaining = max(0, limit - used)
    return {
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "period_end": None,
        "period_label": "session",
        "tier": "anonymous",
        "unlimited": False,
        "chat_history": False,
    }


@transaction.atomic
def consume_assistant_credit(request, *, kind: str, user=None) -> dict:
    from .models import AssistantCreditUsage

    user = user if user is not None else getattr(request, "user", None)
    quota = get_assistant_credit_quota(request, user=user)

    if quota.get("unlimited"):
        sub = _active_paid_subscription(user) if user and user.is_authenticated else None
        AssistantCreditUsage.objects.create(
            user=user if user and user.is_authenticated else None,
            session_key="" if user and user.is_authenticated else _session_key(request),
            subscription=sub,
            kind=kind,
            credits=1,
        )
        return quota

    if quota["remaining"] <= 0:
        raise InsufficientAssistantCredits(quota)

    sub = _active_paid_subscription(user) if user and user.is_authenticated else None
    AssistantCreditUsage.objects.create(
        user=user if user and user.is_authenticated else None,
        session_key="" if user and user.is_authenticated else _session_key(request),
        subscription=sub if sub else None,
        kind=kind,
        credits=1,
    )
    return get_assistant_credit_quota(request, user=user)
