from django.conf import settings
from django.db import models


class Report(models.Model):
    class SourceType(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        AI_GENERATED = "ai_generated", "Platform generated"
        USER_GENERATED = "user_generated", "User generated"

    class AccessType(models.TextChoices):
        FREE = "free", "Free"
        PAID = "paid", "Paid"
        SUBSCRIBER_ONLY = "subscriber_only", "Subscriber only"
        SUBSCRIBER_OR_PAID = "subscriber_or_paid", "Subscriber or paid"

    class ReportFormat(models.TextChoices):
        PDF = "pdf", "PDF"
        WEB_ARTICLE = "web_article", "Web article"
        PDF_AND_ARTICLE = "pdf_and_article", "PDF and web article"

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
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.AI_GENERATED,
    )
    access_type = models.CharField(
        max_length=20,
        choices=AccessType.choices,
        default=AccessType.PAID,
    )
    report_format = models.CharField(
        max_length=20,
        choices=ReportFormat.choices,
        default=ReportFormat.PDF,
    )
    allowed_plans = models.ManyToManyField(
        "subscriptions.SubscriptionPlan",
        blank=True,
        related_name="gated_reports",
    )
    bounding_box = models.JSONField(default=dict, blank=True)
    center_lat = models.FloatField(null=True, blank=True)
    center_lng = models.FloatField(null=True, blank=True)
    zoom = models.PositiveSmallIntegerField(null=True, blank=True)
    article_body = models.JSONField(default=list, blank=True)
    layers = models.ManyToManyField(
        "maps.MapLayer",
        blank=True,
        related_name="linked_reports",
    )
    boundaries = models.ManyToManyField(
        "geography.AdminBoundary",
        blank=True,
        related_name="linked_reports",
    )
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

    @property
    def has_article(self) -> bool:
        return self.report_format in (
            self.ReportFormat.WEB_ARTICLE,
            self.ReportFormat.PDF_AND_ARTICLE,
        )


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


class ReportDocumentChunk(models.Model):
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="document_chunks",
    )
    page_number = models.PositiveIntegerField(default=1)
    chunk_index = models.PositiveIntegerField(default=0)
    text = models.TextField()
    embedding = models.JSONField(default=list, blank=True)
    token_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["page_number", "chunk_index"]
        indexes = [
            models.Index(fields=["report", "page_number"]),
        ]

    def __str__(self):
        return f"{self.report.slug} p{self.page_number} #{self.chunk_index}"


class ReportChatThread(models.Model):
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="chat_threads",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="report_chat_threads",
    )
    messages = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("report", "user")
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user_id} · {self.report.slug}"


class UserExplorationReport(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="exploration_reports",
    )
    title = models.CharField(max_length=255, blank=True)
    prompt = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    context = models.JSONField(default=dict, blank=True)
    revision_notes = models.TextField(blank=True)
    narrative = models.TextField(blank=True)
    sections = models.JSONField(default=dict, blank=True)
    pdf_file = models.FileField(upload_to="exploration_reports/", blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Exploration report {self.id}"
