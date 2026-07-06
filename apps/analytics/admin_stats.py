from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.compliance.models import LicenseAgreement
from apps.payments.models import PaymentOrder
from apps.reports.models import Report
from apps.subscriptions.models import DownloadPurchase, UserSubscription

# Admin dashboard hotspot sampling: full scans over 100k+ features can timeout in production.
ADMIN_HOTSPOT_FEATURE_CAP = 12_000

def _month_key(dt) -> str | None:
    """Bucket a datetime into YYYY-MM without DB-side TruncMonth (MySQL tz-safe)."""
    if not dt:
        return None
    try:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.utc)
        local = timezone.localtime(dt)
        return local.strftime("%Y-%m")
    except (ValueError, TypeError, OverflowError):
        return None


def _monthly_trend(qs, date_field, months=6):
    cutoff = timezone.now() - timedelta(days=months * 31)
    counts: Counter[str] = Counter()
    for dt in qs.filter(**{f"{date_field}__gte": cutoff}).values_list(date_field, flat=True).iterator(
        chunk_size=2000
    ):
        month = _month_key(dt)
        if month:
            counts[month] += 1
    return [{"month": month, "count": counts[month]} for month in sorted(counts)]


def _revenue_trend(months=6):
    cutoff = timezone.now() - timedelta(days=months * 31)
    totals: defaultdict[str, float] = defaultdict(float)
    for created_at, amount in (
        PaymentOrder.objects.filter(
            status=PaymentOrder.Status.COMPLETED,
            created_at__gte=cutoff,
        )
        .values_list("created_at", "amount")
        .iterator(chunk_size=2000)
    ):
        month = _month_key(created_at)
        if month:
            totals[month] += float(amount or 0)
    return [{"month": month, "total": totals[month]} for month in sorted(totals)]


def build_admin_platform_analytics():
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)

    # --- Users ---
    users_qs = User.objects.all()
    total_users = users_qs.count()
    by_role = list(
        users_qs.values("role").annotate(count=Count("id")).order_by("-count")
    )
    new_users_30d = users_qs.filter(created_at__gte=thirty_days_ago).count()
    signup_trend = _monthly_trend(users_qs, "created_at")
    recent_users = []
    for row in users_qs.order_by("-created_at")[:8].values(
        "username", "email", "role", "created_at", "organization"
    ):
        created_at = row.get("created_at")
        try:
            created_iso = created_at.isoformat() if created_at else None
        except (ValueError, TypeError):
            created_iso = None
        recent_users.append({**row, "created_at": created_iso})

    free_count = users_qs.filter(role=User.Role.FREE).count()
    subscriber_count = users_qs.filter(role=User.Role.SUBSCRIBER).count()
    registrable = free_count + subscriber_count
    subscriber_rate = round(subscriber_count / registrable * 100, 1) if registrable else 0

    # --- Subscriptions ---
    subs_qs = UserSubscription.objects.select_related("plan")
    active_subs = subs_qs.filter(status=UserSubscription.Status.ACTIVE).count()
    expired_subs = subs_qs.filter(status=UserSubscription.Status.EXPIRED).count()
    pending_subs = subs_qs.filter(status=UserSubscription.Status.PENDING).count()
    cancelled_subs = subs_qs.filter(status=UserSubscription.Status.CANCELLED).count()
    by_plan = list(
        subs_qs.filter(status=UserSubscription.Status.ACTIVE)
        .values("plan__name", "plan__billing_cycle")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    mrr = Decimal("0")
    for sub in subs_qs.filter(status=UserSubscription.Status.ACTIVE).select_related("plan"):
        if not sub.plan_id or sub.plan is None:
            continue
        price = sub.plan.price or Decimal("0")
        if sub.plan.billing_cycle == "annual":
            mrr += price / 12
        else:
            mrr += price

    expiring_soon = subs_qs.filter(
        status=UserSubscription.Status.ACTIVE,
        end_date__lte=(now.date() + timedelta(days=30)),
        end_date__gte=now.date(),
    ).count()

    # --- Orders & revenue ---
    orders_qs = PaymentOrder.objects.all()
    completed_orders = orders_qs.filter(status=PaymentOrder.Status.COMPLETED)
    total_revenue = float(completed_orders.aggregate(t=Sum("amount"))["t"] or 0)
    revenue_30d = float(
        completed_orders.filter(created_at__gte=thirty_days_ago).aggregate(t=Sum("amount"))["t"] or 0
    )
    revenue_by_type = list(
        completed_orders.values("order_type").annotate(
            total=Sum("amount"), count=Count("id")
        )
    )
    for row in revenue_by_type:
        row["total"] = float(row["total"] or 0)

    order_counts = {
        "total": orders_qs.count(),
        "completed": completed_orders.count(),
        "pending": orders_qs.filter(status=PaymentOrder.Status.PENDING).count(),
        "failed": orders_qs.filter(status=PaymentOrder.Status.FAILED).count(),
    }
    checkout_success = (
        round(order_counts["completed"] / order_counts["total"] * 100, 1)
        if order_counts["total"]
        else 0
    )

    sub_orders = orders_qs.filter(order_type=PaymentOrder.OrderType.SUBSCRIPTION)
    sub_order_total = sub_orders.count()
    sub_order_completed = sub_orders.filter(status=PaymentOrder.Status.COMPLETED).count()
    subscription_checkout_rate = (
        round(sub_order_completed / sub_order_total * 100, 1) if sub_order_total else 0
    )

    # --- Reports ---
    total_reports = Report.objects.filter(is_active=True).count()
    total_downloads = DownloadPurchase.objects.count()
    download_revenue = float(
        DownloadPurchase.objects.aggregate(t=Sum("amount_paid"))["t"] or 0
    )
    top_reports = list(
        DownloadPurchase.objects.values("report__title", "report__id")
        .annotate(purchases=Count("id"), revenue=Sum("amount_paid"))
        .order_by("-purchases")[:5]
    )
    for row in top_reports:
        row["revenue"] = float(row["revenue"] or 0)

    # --- B2B licenses ---
    licenses_qs = LicenseAgreement.objects.all()
    license_counts = {
        "total": licenses_qs.count(),
        "active": licenses_qs.filter(status=LicenseAgreement.Status.ACTIVE).count(),
        "pending": licenses_qs.filter(
            status__in=(LicenseAgreement.Status.PENDING, LicenseAgreement.Status.DRAFT)
        ).count(),
        "approved": licenses_qs.filter(status=LicenseAgreement.Status.APPROVED).count(),
    }

    return {
        "generated_at": now.isoformat(),
        "users": {
            "total": total_users,
            "new_30d": new_users_30d,
            "by_role": by_role,
            "signup_trend": signup_trend,
            "recent": recent_users,
        },
        "conversions": {
            "subscriber_rate": subscriber_rate,
            "checkout_success_rate": checkout_success,
            "subscription_checkout_rate": subscription_checkout_rate,
            "free_users": free_count,
            "paying_subscribers": subscriber_count,
        },
        "subscriptions": {
            "active": active_subs,
            "expired": expired_subs,
            "pending": pending_subs,
            "cancelled": cancelled_subs,
            "expiring_soon": expiring_soon,
            "by_plan": [
                {
                    "plan": row["plan__name"],
                    "billing_cycle": row["plan__billing_cycle"],
                    "count": row["count"],
                }
                for row in by_plan
            ],
            "mrr_estimate": float(mrr),
        },
        "revenue": {
            "total": total_revenue,
            "last_30_days": revenue_30d,
            "by_type": revenue_by_type,
            "monthly_trend": _revenue_trend(),
        },
        "orders": order_counts,
        "reports": {
            "catalog_size": total_reports,
            "total_downloads": total_downloads,
            "download_revenue": download_revenue,
            "top_reports": [
                {
                    "title": row["report__title"],
                    "id": row["report__id"],
                    "purchases": row["purchases"],
                    "revenue": row["revenue"],
                }
                for row in top_reports
            ],
        },
        "licenses": license_counts,
    }
