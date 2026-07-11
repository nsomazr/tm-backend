import uuid

from django.conf import settings
from django.db import models


class PaymentOrder(models.Model):
    class OrderType(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        DOWNLOAD = "download", "Report Download"
        LICENSE = "license", "License Agreement"
        AERIAL = "aerial", "Aerial analysis extension"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_orders",
    )
    order_type = models.CharField(max_length=20, choices=OrderType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TZS")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    merchant_reference = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    order_tracking_id = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=100, blank=True)
    payment_provider = models.CharField(
        max_length=20,
        choices=[
            ("snippe", "Snippe"),
            ("simulated", "Simulated"),
        ],
        default="simulated",
    )
    msisdn = models.CharField(max_length=20, blank=True)
    subscription = models.ForeignKey(
        "subscriptions.UserSubscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_orders",
    )
    report = models.ForeignKey(
        "reports.Report",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_orders",
    )
    license_agreement = models.ForeignKey(
        "compliance.LicenseAgreement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_orders",
    )
    gateway_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.merchant_reference} - {self.status}"


class Invoice(models.Model):
    invoice_number = models.CharField(max_length=50, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    payment_order = models.OneToOneField(
        PaymentOrder,
        on_delete=models.CASCADE,
        related_name="invoice",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TZS")
    description = models.TextField(blank=True)
    pdf_file = models.FileField(upload_to="invoices/", blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_sent_to = models.EmailField(blank=True)
    email_send_count = models.PositiveIntegerField(default=0)
    email_last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return self.invoice_number


class Receipt(models.Model):
    receipt_number = models.CharField(max_length=50, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="receipts",
    )
    payment_order = models.OneToOneField(
        PaymentOrder,
        on_delete=models.CASCADE,
        related_name="receipt",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TZS")
    description = models.TextField(blank=True)
    pdf_file = models.FileField(upload_to="receipts/", blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_sent_to = models.EmailField(blank=True)
    email_send_count = models.PositiveIntegerField(default=0)
    email_last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return self.receipt_number


class DocumentEmailLog(models.Model):
    class DocumentType(models.TextChoices):
        INVOICE = "invoice", "Invoice"
        RECEIPT = "receipt", "Receipt"

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    payment_order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.CASCADE,
        related_name="document_emails",
    )
    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    document_number = models.CharField(max_length=50, blank=True)
    sent_to = models.EmailField()
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_document_emails",
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.document_type} → {self.sent_to} ({self.status})"
