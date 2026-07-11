from django.contrib import admin

from .models import DocumentEmailLog, Invoice, PaymentOrder, Receipt


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = (
        "merchant_reference",
        "user",
        "order_type",
        "amount",
        "currency",
        "status",
        "payment_provider",
        "msisdn",
        "created_at",
    )
    list_filter = ("order_type", "status", "payment_provider", "currency")
    search_fields = ("merchant_reference", "order_tracking_id", "user__email", "user__username", "msisdn")
    readonly_fields = ("gateway_response", "created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "user",
        "amount",
        "currency",
        "issued_at",
        "email_sent_at",
        "email_send_count",
    )
    search_fields = ("invoice_number", "user__email", "email_sent_to")
    readonly_fields = ("issued_at", "email_sent_at", "email_send_count", "email_last_error")


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "receipt_number",
        "user",
        "amount",
        "currency",
        "issued_at",
        "email_sent_at",
        "email_send_count",
    )
    search_fields = ("receipt_number", "user__email", "email_sent_to")
    readonly_fields = ("issued_at", "email_sent_at", "email_send_count", "email_last_error")


@admin.register(DocumentEmailLog)
class DocumentEmailLogAdmin(admin.ModelAdmin):
    list_display = ("document_type", "document_number", "sent_to", "status", "sent_by", "created_at")
    list_filter = ("document_type", "status")
    search_fields = ("document_number", "sent_to", "payment_order__merchant_reference")
    readonly_fields = ("created_at",)
