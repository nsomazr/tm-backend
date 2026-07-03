"""Report catalog access: preview vs full exploration and download quotas."""

from __future__ import annotations

from django.utils import timezone

from apps.accounts.models import User
from apps.subscriptions.models import DownloadPurchase, SubscriptionPlan, SubscriptionReportDownload, UserSubscription


def user_has_report_detail_access(user, report=None) -> bool:
    if not user.is_authenticated:
        return False
    if user.has_paid_access or user.is_admin_user:
        return True
    if user.role == User.Role.MINERAL_MANAGER:
        return True
    if report is not None:
        return report.purchases.filter(user=user).exists()
    return False


def _active_paid_subscription(user) -> UserSubscription | None:
    if not user.is_authenticated or not user.has_paid_access:
        return None

    from django.conf import settings

    from apps.payments.models import PaymentOrder

    today = timezone.now().date()
    qs = UserSubscription.objects.filter(
        user=user,
        status=UserSubscription.Status.ACTIVE,
        start_date__lte=today,
        end_date__gte=today,
    ).select_related("plan")
    qs = qs.filter(payment_orders__status=PaymentOrder.Status.COMPLETED)
    if not getattr(settings, "PAYMENTS_SIMULATE", False):
        qs = qs.exclude(payment_orders__payment_provider="simulated")
    return qs.order_by("-end_date").distinct().first()


def _plan_download_limit(plan) -> int:
    if plan.included_report_downloads:
        return plan.included_report_downloads
    if plan.billing_cycle == SubscriptionPlan.BillingCycle.ANNUAL:
        return 10
    return 3


def get_subscription_download_quota(user) -> dict | None:
    if not user.is_authenticated:
        return None
    if user.is_admin_user or user.role == User.Role.MINERAL_MANAGER:
        return {
            "limit": None,
            "used": 0,
            "remaining": None,
            "period_end": None,
            "billing_cycle": None,
            "unlimited": True,
        }

    sub = _active_paid_subscription(user)
    if not sub:
        return None

    limit = _plan_download_limit(sub.plan)
    used = SubscriptionReportDownload.objects.filter(subscription=sub, user=user).count()
    remaining = max(0, limit - used)

    return {
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "period_end": sub.end_date.isoformat() if sub.end_date else None,
        "billing_cycle": sub.plan.billing_cycle,
        "unlimited": False,
    }


def user_can_download_report(user, report) -> tuple[bool, str | None]:
    if not user.is_authenticated:
        return False, None
    if user.is_admin_user or user.role == User.Role.MINERAL_MANAGER:
        return True, "admin"
    if DownloadPurchase.objects.filter(user=user, report=report).exists():
        return True, "purchase"

    sub = _active_paid_subscription(user)
    if not sub:
        return False, None

    if SubscriptionReportDownload.objects.filter(
        subscription=sub, user=user, report=report
    ).exists():
        return True, "subscription"

    limit = _plan_download_limit(sub.plan)
    used = SubscriptionReportDownload.objects.filter(subscription=sub, user=user).count()
    if used < limit:
        return True, "subscription"

    return False, None


def record_subscription_download(user, report) -> None:
    sub = _active_paid_subscription(user)
    if not sub:
        return
    if DownloadPurchase.objects.filter(user=user, report=report).exists():
        return
    SubscriptionReportDownload.objects.get_or_create(
        user=user,
        report=report,
        subscription=sub,
    )
