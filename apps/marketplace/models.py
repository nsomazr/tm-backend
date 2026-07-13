from django.conf import settings
from django.db import models


class MarketplaceListing(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        HIDDEN = "hidden", "Hidden"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="marketplace_listings",
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=80, unique=True)
    summary = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    geometry = models.JSONField(
        default=dict,
        blank=True,
        help_text="GeoJSON Point, MultiPoint, Polygon, or MultiPolygon for the marketed area.",
    )
    buffer_km = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Optional buffer (km) around geometry; max 20.",
    )
    center_lat = models.FloatField(null=True, blank=True)
    center_lng = models.FloatField(null=True, blank=True)
    bounding_box = models.JSONField(default=dict, blank=True)
    commodity_labels = models.JSONField(
        default=list,
        blank=True,
        help_text="Free-text commodity tags shown on the listing.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    show_on_map = models.BooleanField(
        default=True,
        help_text="When false, published listings stay out of the public map.",
    )
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    show_contact_public = models.BooleanField(default=False)
    allow_inquiries = models.BooleanField(default=True)
    country = models.ForeignKey(
        "geography.Country",
        on_delete=models.PROTECT,
        related_name="marketplace_listings",
        null=True,
        blank=True,
    )
    view_count = models.PositiveIntegerField(default=0)
    map_click_count = models.PositiveIntegerField(default=0)
    document_download_count = models.PositiveIntegerField(default=0)
    terra_summary_count = models.PositiveIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status", "show_on_map"]),
            models.Index(fields=["owner", "status"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_publicly_visible(self) -> bool:
        return (
            self.deleted_at is None
            and self.status == self.Status.PUBLISHED
            and self.show_on_map
            and bool(self.geometry)
        )


class ListingDocument(models.Model):
    listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="marketplace/documents/")
    is_public = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="marketplace_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class ListingInquiry(models.Model):
    listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.CASCADE,
        related_name="inquiries",
    )
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="marketplace_inquiries_sent",
    )
    message = models.TextField()
    contact_email = models.EmailField(blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["listing", "is_read"]),
        ]

    def __str__(self):
        return f"Inquiry on {self.listing_id} from {self.from_user_id}"


class ListingEvent(models.Model):
    class Kind(models.TextChoices):
        VIEW = "view", "View"
        MAP_CLICK = "map_click", "Map click"
        DOCUMENT_DOWNLOAD = "document_download", "Document download"
        TERRA_SUMMARY = "terra_summary", "Terra summary"

    listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.CASCADE,
        related_name="events",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_events",
    )
    session_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["listing", "kind", "created_at"]),
            models.Index(fields=["kind", "created_at"]),
        ]

    def __str__(self):
        return f"{self.kind} on listing {self.listing_id}"
