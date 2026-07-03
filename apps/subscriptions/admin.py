from django.contrib import admin

from .models import DownloadPurchase, SubscriptionPlan, UserSubscription


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "billing_cycle",
        "price",
        "currency",
        "included_assistant_credits",
        "included_report_downloads",
        "is_active",
    )
    filter_horizontal = ("included_minerals",)


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "start_date", "end_date", "auto_renew")
    list_filter = ("status", "plan")


@admin.register(DownloadPurchase)
class DownloadPurchaseAdmin(admin.ModelAdmin):
    list_display = ("user", "report", "amount_paid", "purchased_at")
