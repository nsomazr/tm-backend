from django.conf import settings
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.Model):
    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        ANNUAL = "annual", "Annual"

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    billing_cycle = models.CharField(max_length=10, choices=BillingCycle.choices)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TZS")
    included_minerals = models.ManyToManyField(
        "minerals.Mineral",
        blank=True,
        related_name="subscription_plans",
    )
    included_report_downloads = models.PositiveSmallIntegerField(
        default=0,
        help_text="PDF downloads included per billing period (e.g. 3 monthly, 10 annual).",
    )
    included_assistant_credits = models.PositiveIntegerField(
        default=0,
        help_text="Ask Terra AI credits included per calendar month (e.g. 3000 monthly plan, 5000 annual plan).",
    )
    includes_chat_history = models.BooleanField(
        default=False,
        help_text="Subscribers can persist Ask Terra chat threads across sessions.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price"]

    def __str__(self):
        return f"{self.name} ({self.billing_cycle})"


class UserSubscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
        PENDING = "pending", "Pending Payment"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="user_subscriptions",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.plan.name}"

    @property
    def is_paid(self):
        from django.conf import settings

        from apps.payments.models import PaymentOrder

        qs = self.payment_orders.filter(status=PaymentOrder.Status.COMPLETED)
        if not getattr(settings, "PAYMENTS_SIMULATE", False):
            qs = qs.exclude(payment_provider="simulated")
        return qs.exists()

    @property
    def is_active(self):
        if self.status != self.Status.ACTIVE:
            return False
        if self.end_date and self.end_date < timezone.now().date():
            return False
        return self.is_paid

    @property
    def days_until_expiry(self):
        if not self.end_date:
            return None
        return (self.end_date - timezone.now().date()).days


class DownloadPurchase(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="download_purchases",
    )
    report = models.ForeignKey(
        "reports.Report",
        on_delete=models.CASCADE,
        related_name="purchases",
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TZS")
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "report")

    def __str__(self):
        return f"{self.user.username} purchased {self.report.title}"


class SubscriptionReportDownload(models.Model):
    """Tracks report PDF downloads consumed from a subscriber's included quota."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription_report_downloads",
    )
    report = models.ForeignKey(
        "reports.Report",
        on_delete=models.CASCADE,
        related_name="subscription_downloads",
    )
    subscription = models.ForeignKey(
        UserSubscription,
        on_delete=models.CASCADE,
        related_name="report_downloads",
    )
    downloaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "report", "subscription")

    def __str__(self):
        return f"{self.user.username} downloaded {self.report.title} (quota)"
