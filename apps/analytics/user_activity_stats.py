from collections import Counter
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from .admin_stats import _monthly_trend
from .models import AssistantChatThread, AssistantCreditUsage, MineralExplorationLog


def build_admin_user_activity_analytics() -> dict:
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)

    explorations_qs = MineralExplorationLog.objects.select_related("user")
    credits_qs = AssistantCreditUsage.objects.select_related("user")

    explorations_30d = explorations_qs.filter(created_at__gte=thirty_days_ago)
    credits_30d = credits_qs.filter(created_at__gte=thirty_days_ago)

    credits_by_kind = list(
        credits_30d.values("kind")
        .annotate(events=Count("id"), credits=Sum("credits"))
        .order_by("-credits")
    )
    for row in credits_by_kind:
        row["credits"] = int(row["credits"] or 0)

    kind_totals = {row["kind"]: row for row in credits_by_kind}
    map_insights_30d = kind_totals.get(AssistantCreditUsage.Kind.MAP_INSIGHT, {}).get("events", 0)
    chats_30d = kind_totals.get(AssistantCreditUsage.Kind.CHAT, {}).get("events", 0)
    exports_30d = kind_totals.get(AssistantCreditUsage.Kind.REPORT_EXPORT, {}).get("events", 0)
    report_chat_30d = kind_totals.get(AssistantCreditUsage.Kind.REPORT_CHAT, {}).get("events", 0)
    exploration_generate_30d = kind_totals.get(AssistantCreditUsage.Kind.EXPLORATION_GENERATE, {}).get("events", 0)
    exploration_export_30d = kind_totals.get(AssistantCreditUsage.Kind.EXPLORATION_EXPORT, {}).get("events", 0)
    credits_used_30d = sum(row["credits"] for row in credits_by_kind)

    from apps.reports.models import Report, UserExplorationReport

    reports_by_access = list(
        Report.objects.filter(is_active=True)
        .values("access_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    exploration_reports_30d = UserExplorationReport.objects.filter(created_at__gte=thirty_days_ago).count()

    top_explored_minerals = list(
        explorations_qs.values("mineral_slug")
        .annotate(
            explorations=Count("id"),
            unique_users=Count("user", distinct=True),
        )
        .order_by("-explorations")[:12]
    )

    explored_minerals_30d = list(
        explorations_30d.values("mineral_slug")
        .annotate(explorations=Count("id"))
        .order_by("-explorations")[:12]
    )

    user_scores: Counter[int] = Counter()
    user_labels: dict[int, str] = {}
    for row in (
        credits_30d.filter(user__isnull=False)
        .values("user_id", "user__username")
        .annotate(score=Sum("credits"))
        .order_by("-score")[:8]
    ):
        user_scores[row["user_id"]] = int(row["score"] or 0)
        user_labels[row["user_id"]] = row["user__username"]

    for row in (
        explorations_30d.values("user_id", "user__username")
        .annotate(score=Count("id"))
        .order_by("-score")[:8]
    ):
        user_scores[row["user_id"]] += int(row["score"] or 0)
        user_labels.setdefault(row["user_id"], row["user__username"])

    top_active_users = [
        {
            "user_id": user_id,
            "username": user_labels.get(user_id, "unknown"),
            "activity_score": score,
        }
        for user_id, score in user_scores.most_common(8)
    ]

    recent_explorations = [
        {
            "username": row.user.username if row.user_id else "unknown",
            "mineral_slug": row.mineral_slug,
            "created_at": row.created_at.isoformat(),
        }
        for row in explorations_qs.order_by("-created_at")[:15]
    ]

    recent_assistant_usage = [
        {
            "username": row.user.username if row.user_id else "anonymous",
            "kind": row.kind,
            "credits": row.credits,
            "created_at": row.created_at.isoformat(),
        }
        for row in credits_qs.order_by("-created_at")[:15]
    ]

    return {
        "generated_at": now.isoformat(),
        "summary": {
            "explorations_30d": explorations_30d.count(),
            "unique_explorers_30d": explorations_30d.values("user").distinct().count(),
            "assistant_events_30d": credits_30d.count(),
            "assistant_credits_30d": credits_used_30d,
            "map_insights_30d": map_insights_30d,
            "assistant_chats_30d": chats_30d,
            "report_exports_30d": exports_30d,
            "report_chat_30d": report_chat_30d,
            "exploration_generate_30d": exploration_generate_30d,
            "exploration_export_30d": exploration_export_30d,
            "exploration_reports_30d": exploration_reports_30d,
            "catalog_reports_by_access": reports_by_access,
            "active_assistant_users_30d": credits_30d.filter(user__isnull=False)
            .values("user")
            .distinct()
            .count(),
            "chat_threads_total": AssistantChatThread.objects.count(),
            "chat_threads_active_30d": AssistantChatThread.objects.filter(
                updated_at__gte=thirty_days_ago
            ).count(),
        },
        "explored_minerals": top_explored_minerals,
        "explored_minerals_30d": explored_minerals_30d,
        "assistant_by_kind": credits_by_kind,
        "exploration_trend": _monthly_trend(explorations_qs, "created_at"),
        "assistant_trend": _monthly_trend(credits_qs, "created_at"),
        "top_active_users": top_active_users,
        "recent_explorations": recent_explorations,
        "recent_assistant_usage": recent_assistant_usage,
    }
