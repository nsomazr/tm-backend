from django.conf import settings
from django.db import models
from django.utils.text import slugify


class MineralCategory(models.Model):
    name = models.CharField(max_length=100)
    name_sw = models.CharField(max_length=100, blank=True)
    slug = models.SlugField(unique=True)
    color = models.CharField(max_length=7, default="#000000")
    description = models.TextField(blank=True)
    priority = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "mineral categories"
        ordering = ["priority", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Mineral(models.Model):
    name = models.CharField(max_length=100)
    name_sw = models.CharField(max_length=100, blank=True)
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(
        MineralCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="minerals",
    )
    country = models.ForeignKey(
        "geography.Country",
        on_delete=models.CASCADE,
        related_name="minerals",
    )
    color = models.CharField(max_length=7, default="#E87722")
    color_rgba = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="RGBA fill derived from color hex (e.g. rgba(232,119,34,0.55))",
    )
    icon = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    associated_layers = models.ManyToManyField(
        "maps.MapLayer",
        blank=True,
        related_name="associated_minerals",
        help_text=(
            "Extra map layers (structures, points, etc.) included when this "
            "commodity is selected for heatmap / catalog overlay."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        if self.color:
            from .color_utils import hex_to_rgba, normalize_hex

            self.color = normalize_hex(self.color, fallback=self.color)
            self.color_rgba = hex_to_rgba(self.color, 0.55)
        super().save(*args, **kwargs)


class MineralManagerAssignment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mineral_assignments",
    )
    mineral = models.ForeignKey(
        Mineral,
        on_delete=models.CASCADE,
        related_name="manager_assignments",
    )
    can_publish = models.BooleanField(default=False)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "mineral")
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.user.username} -> {self.mineral.name}"
