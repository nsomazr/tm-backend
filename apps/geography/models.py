from django.db import models


class Country(models.Model):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=100)
    name_sw = models.CharField(max_length=100, blank=True)
    center_lat = models.FloatField(null=True, blank=True)
    center_lng = models.FloatField(null=True, blank=True)
    default_zoom = models.PositiveSmallIntegerField(default=6)
    bounds = models.JSONField(
        default=dict,
        blank=True,
        help_text='Bounding box: {"west", "south", "east", "north"}',
    )
    boundary = models.JSONField(
        default=dict,
        blank=True,
        help_text="GeoJSON geometry for country outline",
    )
    coordinate_system = models.CharField(
        max_length=32,
        default="arc1960",
        help_text="Default map coordinate reference system for this country.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "countries"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Region(models.Model):
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name="regions")
    name = models.CharField(max_length=100)
    name_sw = models.CharField(max_length=100, blank=True)
    bounds = models.JSONField(default=dict, blank=True, help_text="GeoJSON bounding box")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("country", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}, {self.country.code}"


class AdminBoundary(models.Model):
    class Level(models.IntegerChoices):
        COUNTRY = 0, "Country"
        REGION = 1, "Region"
        DISTRICT = 2, "District"
        WARD = 3, "Ward"
        VILLAGE = 4, "Village"

    class Source(models.TextChoices):
        GADM = "gadm", "GADM"
        ADMIN_UPLOAD = "admin_upload", "Admin upload"
        PRESET = "preset", "Preset"

    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name="admin_boundaries")
    level = models.PositiveSmallIntegerField(choices=Level.choices)
    name = models.CharField(max_length=200)
    name_sw = models.CharField(max_length=200, blank=True)
    code = models.CharField(max_length=64)
    geometry = models.JSONField(help_text="GeoJSON Polygon or MultiPolygon")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.PRESET)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_boundaries",
    )
    center_lat = models.FloatField(null=True, blank=True)
    center_lng = models.FloatField(null=True, blank=True)
    geological_summary = models.TextField(
        blank=True,
        help_text="Local or regional geological summary for Terra insights (English).",
    )
    geological_summary_sw = models.TextField(blank=True)
    geological_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Structured geology: scope, formations, lithology, stratigraphy, age, data_sources.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "geographic boundary"
        verbose_name_plural = "geographic boundaries"
        unique_together = ("country", "level", "code")
        ordering = ["level", "name"]
        indexes = [
            models.Index(fields=["country", "level"]),
        ]

    def __str__(self):
        return f"{self.name} (L{self.level}, {self.country.code})"


class BoundaryGeologyDocument(models.Model):
    class Scope(models.TextChoices):
        LOCAL = "local", "Local"
        REGIONAL = "regional", "Regional"
        GLOBAL = "global", "Global reference"

    boundary = models.ForeignKey(
        AdminBoundary,
        on_delete=models.CASCADE,
        related_name="geology_documents",
    )
    title = models.CharField(max_length=200)
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.LOCAL)
    file = models.FileField(upload_to="boundary_geology/")
    extracted_text = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="boundary_geology_uploads",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.boundary.name})"


class GeoReference(models.Model):
    """
    Admin-only geological reference datasets (shapefile / GeoJSON uploads).

    Used privately to improve Ask Terra insights. Never exposed on the public map
    or mentioned to normal users.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    country = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="geo_references",
    )
    source_file = models.FileField(upload_to="geo_references/", blank=True)
    source_filename = models.CharField(max_length=255, blank=True)
    feature_count = models.PositiveIntegerField(default=0)
    bounds = models.JSONField(
        default=dict,
        blank=True,
        help_text='Bounding box: {"west", "south", "east", "north"}',
    )
    is_active = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="geo_reference_uploads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "geo reference"
        verbose_name_plural = "geo references"

    def __str__(self):
        return self.name


class GeoReferenceFeature(models.Model):
    geo_reference = models.ForeignKey(
        GeoReference,
        on_delete=models.CASCADE,
        related_name="features",
    )
    geometry = models.JSONField()
    properties = models.JSONField(default=dict, blank=True)
    label = models.CharField(max_length=255, blank=True)
    # Stored bbox so MySQL can filter without sorting/loading huge geometry JSON.
    min_lng = models.FloatField(null=True, blank=True, db_index=True)
    min_lat = models.FloatField(null=True, blank=True, db_index=True)
    max_lng = models.FloatField(null=True, blank=True, db_index=True)
    max_lat = models.FloatField(null=True, blank=True, db_index=True)

    class Meta:
        # No default ordering: ORDER BY on rows with large JSON geometries blows
        # MySQL sort_buffer (error 1038) on geojson / near-point scans.
        ordering = []

    def __str__(self):
        return self.label or f"Feature {self.pk}"
