from django.conf import settings
from django.db import models


class MapLayer(models.Model):
    class LayerType(models.TextChoices):
        POLYGON = "polygon", "Polygon"
        POINT = "point", "Point"
        LINE = "line", "Line"

    name = models.CharField(max_length=200)
    name_sw = models.CharField(max_length=200, blank=True)
    slug = models.SlugField(max_length=220)
    layer_type = models.CharField(max_length=10, choices=LayerType.choices)
    mineral = models.ForeignKey(
        "minerals.Mineral",
        on_delete=models.CASCADE,
        related_name="layers",
    )
    region = models.ForeignKey(
        "geography.Region",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="layers",
    )
    z_index = models.IntegerField(default=0)
    is_preview = models.BooleanField(
        default=False,
        help_text="Visible to free-tier users",
    )
    is_active = models.BooleanField(default=True)
    style = models.JSONField(
        default=dict,
        blank=True,
        help_text="fill, stroke, strokeWidth, hatch pattern",
    )
    description = models.TextField(blank=True)
    current_version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_layers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("mineral", "slug")
        ordering = ["z_index", "name"]

    def __str__(self):
        return f"{self.name} ({self.layer_type})"


class MapFeature(models.Model):
    layer = models.ForeignKey(
        MapLayer,
        on_delete=models.CASCADE,
        related_name="features",
    )
    geometry = models.JSONField(help_text="GeoJSON geometry object")
    properties = models.JSONField(default=dict, blank=True)
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    label = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_features",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.label or f"Feature {self.id} on {self.layer.name}"


class LayerVersion(models.Model):
    layer = models.ForeignKey(
        MapLayer,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    changelog = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    file = models.FileField(upload_to="layer_uploads/", blank=True)
    feature_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("layer", "version_number")
        ordering = ["-version_number"]

    def __str__(self):
        return f"{self.layer.name} v{self.version_number}"


class LayerUpload(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    layer = models.ForeignKey(
        MapLayer,
        on_delete=models.CASCADE,
        related_name="uploads",
    )
    file = models.FileField(upload_to="layer_imports/")
    file_type = models.CharField(max_length=20, default="geojson")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error_message = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Upload {self.id} for {self.layer.name}"


class SavedExploration(models.Model):
    """A paid user's saved draw-and-explore area (point / line / polygon)."""

    class Mode(models.TextChoices):
        POINT = "point", "Point"
        LINE = "line", "Line"
        POLYGON = "polygon", "Polygon"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_explorations",
    )
    name = models.CharField(max_length=120)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.POINT)
    points = models.JSONField(help_text="List of [lng, lat] WGS84 vertices.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.mode}) - {self.user_id}"


class MapPlatformSettings(models.Model):
    """Singleton platform-wide map display settings."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    coordinate_system = models.CharField(max_length=32, default="arc1960")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Map platform settings"
        verbose_name_plural = "Map platform settings"

    def __str__(self):
        return f"Map settings (CRS: {self.coordinate_system})"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={"coordinate_system": "arc1960"},
        )
        return obj

