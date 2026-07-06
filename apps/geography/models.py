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
