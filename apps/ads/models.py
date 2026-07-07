from django.conf import settings
from django.db import models
from django.utils import timezone


class AdPlacement(models.TextChoices):
    MAP_SIDEBAR = "map_sidebar", "Map sidebar"
    MAP_OVERLAY = "map_overlay", "Map overlay"
    DOWNLOADS_BANNER = "downloads_banner", "Downloads catalog"
    SUBSCRIPTIONS_BANNER = "subscriptions_banner", "Subscriptions page"
    DASHBOARD_CARD = "dashboard_card", "User dashboard"
    ABOUT_BANNER = "about_banner", "About page"


class AdAudience(models.TextChoices):
    ALL = "all", "All visitors"
    FREE = "free", "Free users only"
    SUBSCRIBER = "subscriber", "Paid subscribers only"


class Ad(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    company_name = models.CharField(max_length=200)
    headline = models.CharField(max_length=300, blank=True)
    body_text = models.TextField(blank=True)
    image = models.ImageField(upload_to="ads/", blank=True)
    cta_label = models.CharField(max_length=80, default="Learn more")
    link_url = models.URLField(max_length=500)
    open_in_new_tab = models.BooleanField(default=True)
    placements = models.JSONField(default=list, blank=True)
    priority = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_hidden = models.BooleanField(
        default=False,
        help_text="Hide from public surfaces without deleting the campaign.",
    )
    audience = models.CharField(
        max_length=20,
        choices=AdAudience.choices,
        default=AdAudience.ALL,
    )
    country_codes = models.JSONField(
        default=list,
        blank=True,
        help_text="ISO country codes. Empty list means all countries.",
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    impression_count = models.PositiveIntegerField(default=0)
    click_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "-created_at"]

    def __str__(self):
        return f"{self.company_name}: {self.title}"

    @property
    def click_through_rate(self) -> float:
        if self.impression_count <= 0:
            return 0.0
        return round((self.click_count / self.impression_count) * 100, 2)

    def is_live(self, *, now=None) -> bool:
        now = now or timezone.now()
        if not self.is_active or self.is_hidden:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        return True


class AdEvent(models.Model):
    class Kind(models.TextChoices):
        IMPRESSION = "impression", "Impression"
        CLICK = "click", "Click"

    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    placement = models.CharField(max_length=40, choices=AdPlacement.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ad_events",
    )
    session_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ad", "kind", "created_at"]),
            models.Index(fields=["placement", "created_at"]),
        ]
