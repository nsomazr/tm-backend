"""Report catalog access: preview vs full exploration and download quotas."""

from __future__ import annotations

from django.utils import timezone

from apps.accounts.models import User
from apps.subscriptions.models import DownloadPurchase, SubscriptionPlan, SubscriptionReportDownload, UserSubscription

from .models import Report


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


def _user_on_allowed_plan(user, report: Report) -> bool:
    sub = _active_paid_subscription(user)
    if not sub:
        return False
    allowed = report.allowed_plans.all()
    if not allowed.exists():
        return True
    return allowed.filter(pk=sub.plan_id).exists()


def _is_staff_or_manager(user) -> bool:
    return user.is_authenticated and (
        user.is_admin_user or user.role == User.Role.MINERAL_MANAGER
    )


def user_has_report_detail_access(user, report: Report | None = None) -> bool:
    if _is_staff_or_manager(user):
        return True

    if report is None:
        if not user.is_authenticated:
            return False
        if user.has_paid_access:
            return True
        return False

    access_type = report.access_type or Report.AccessType.PAID

    if access_type == Report.AccessType.FREE:
        return True

    if not user.is_authenticated:
        return False

    if DownloadPurchase.objects.filter(user=user, report=report).exists():
        return True

    if access_type in (
        Report.AccessType.SUBSCRIBER_ONLY,
        Report.AccessType.SUBSCRIBER_OR_PAID,
    ):
        if _user_on_allowed_plan(user, report):
            return True

    if access_type == Report.AccessType.PAID and user.has_paid_access:
        return True

    if access_type == Report.AccessType.SUBSCRIBER_OR_PAID:
        return False

    return False


def _plan_download_limit(plan) -> int:
    if plan.included_report_downloads:
        return plan.included_report_downloads
    if plan.billing_cycle == SubscriptionPlan.BillingCycle.ANNUAL:
        return 10
    return 3


def get_subscription_download_quota(user) -> dict | None:
    if not user.is_authenticated:
        return None
    if _is_staff_or_manager(user):
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


def user_can_download_report(user, report: Report) -> tuple[bool, str | None]:
    if not user.is_authenticated:
        return False, None

    if _is_staff_or_manager(user):
        return True, "admin"

    access_type = report.access_type or Report.AccessType.PAID

    if access_type == Report.AccessType.FREE:
        return True, "free"

    if DownloadPurchase.objects.filter(user=user, report=report).exists():
        return True, "purchase"

    if access_type in (
        Report.AccessType.SUBSCRIBER_ONLY,
        Report.AccessType.SUBSCRIBER_OR_PAID,
    ):
        if not _user_on_allowed_plan(user, report):
            if access_type == Report.AccessType.SUBSCRIBER_ONLY:
                return False, None
        else:
            sub = _active_paid_subscription(user)
            if sub:
                if SubscriptionReportDownload.objects.filter(
                    subscription=sub, user=user, report=report
                ).exists():
                    return True, "subscription"
                limit = _plan_download_limit(sub.plan)
                used = SubscriptionReportDownload.objects.filter(
                    subscription=sub, user=user
                ).count()
                if used < limit:
                    return True, "subscription"

    if access_type in (Report.AccessType.PAID, Report.AccessType.SUBSCRIBER_OR_PAID):
        return False, None

    return False, None


def record_subscription_download(user, report: Report) -> None:
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
