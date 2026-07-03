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
    icon = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
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
