from django.conf import settings
from django.db import models


class AssistantCreditUsage(models.Model):
    """Tracks Ask Terra AI credit consumption (map insights + chat)."""

    class Kind(models.TextChoices):
        MAP_INSIGHT = "map_insight", "Map insight"
        CHAT = "chat", "Chat message"

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
