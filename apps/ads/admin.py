from django.contrib import admin

from .models import Ad, AdEvent


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "company_name",
        "is_active",
        "is_hidden",
        "impression_count",
        "click_count",
        "starts_at",
        "ends_at",
    )
    list_filter = ("is_active", "is_hidden", "audience")
    search_fields = ("title", "company_name", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(AdEvent)
class AdEventAdmin(admin.ModelAdmin):
    list_display = ("ad", "kind", "placement", "user", "created_at")
    list_filter = ("kind", "placement")
