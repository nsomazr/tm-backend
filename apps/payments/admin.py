from django.contrib import admin

from .models import Invoice, PaymentOrder


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
    list_display = ("invoice_number", "user", "amount", "currency", "issued_at")
    search_fields = ("invoice_number", "user__email")
