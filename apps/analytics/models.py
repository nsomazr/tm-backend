from django.conf import settings
from django.db import models


class AssistantCreditUsage(models.Model):
    """Tracks Ask Terra credit consumption (map insights + chat)."""

    class Kind(models.TextChoices):
        MAP_INSIGHT = "map_insight", "Map insight"
        CHAT = "chat", "Chat message"
        REPORT_EXPORT = "report_export", "Insight report export"
        REPORT_CHAT = "report_chat", "Report PDF chat"
        EXPLORATION_GENERATE = "exploration_generate", "Exploration report generate"
        EXPLORATION_REFINE = "exploration_refine", "Exploration report refine"
        EXPLORATION_EXPORT = "exploration_export", "Exploration report export"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_credit_usages",
        null=True,
        blank=True,
    )
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    subscription = models.ForeignKey(
        "subscriptions.UserSubscription",
        on_delete=models.SET_NULL,
        related_name="assistant_credit_usages",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    credits = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["session_key", "created_at"]),
            models.Index(fields=["subscription", "created_at"]),
        ]

    def __str__(self):
        who = self.user.username if self.user_id else self.session_key[:8] or "anon"
        return f"{who} · {self.kind} · {self.credits}"


class AssistantChatThread(models.Model):
    """Saved Ask Terra conversations (paid subscribers)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_chat_threads",
    )
    thread_key = models.CharField(max_length=120)
    messages = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        unique_together = ("user", "thread_key")
        indexes = [
            models.Index(fields=["user", "thread_key"]),
        ]

    def __str__(self):
        return f"{self.user_id} · {self.thread_key} · {len(self.messages or [])} msgs"


class AerialAnalysisGrant(models.Model):
    """Paid extension to analyse map areas larger than the included km² allowance."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="aerial_grants",
    )
    payment_order = models.ForeignKey(
        "payments.PaymentOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aerial_grants",
    )
    lat = models.FloatField()
    lng = models.FloatField()
    zoom = models.PositiveSmallIntegerField(default=8)
    max_area_km2 = models.FloatField()
    purchased_extra_km2 = models.FloatField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def covers_click(self, lat: float, lng: float) -> bool:
        if not self.is_active:
            return False
        from .map_view_area import point_in_analysis_zone

        return point_in_analysis_zone(lat, lng, self.lat, self.lng, self.max_area_km2)

    def covers(self, lat: float, lng: float, zoom: int, area_km2: float) -> bool:
        if not self.covers_click(lat, lng):
            return False
        return area_km2 <= self.max_area_km2

    def __str__(self):
        return f"{self.user_id} · {self.max_area_km2} km² @ {self.lat:.2f},{self.lng:.2f}"


class MineralExplorationLog(models.Model):
    """Tracks unique minerals a user deep-explores (coverage / heatmap) per period."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mineral_exploration_logs",
    )
    mineral_slug = models.SlugField(max_length=220)
    subscription = models.ForeignKey(
        "subscriptions.UserSubscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mineral_exploration_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "mineral_slug", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} · {self.mineral_slug}"
