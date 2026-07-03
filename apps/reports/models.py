from django.conf import settings
from django.db import models


class Report(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    mineral = models.ForeignKey(
        "minerals.Mineral",
        on_delete=models.CASCADE,
        related_name="reports",
    )
    region = models.ForeignKey(
        "geography.Region",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    description = models.TextField(blank=True)
    bounding_box = models.JSONField(default=dict, blank=True)
    pdf_file = models.FileField(upload_to="reports/", blank=True)
    preview_image = models.ImageField(upload_to="report_previews/", blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TZS")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class ReportSummary(models.Model):
    report = models.OneToOneField(
        Report,
        on_delete=models.CASCADE,
        related_name="ai_summary",
    )
    summary = models.TextField()
    key_findings = models.JSONField(default=list, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    model_used = models.CharField(max_length=50, default="gpt-4o-mini")

    def __str__(self):
        return f"Summary for {self.report.title}"
