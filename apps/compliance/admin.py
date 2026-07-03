from django.contrib import admin

from .models import AuditLog, LicenseAgreement, TermsAcceptance, TermsVersion


@admin.register(LicenseAgreement)
class LicenseAgreementAdmin(admin.ModelAdmin):
    list_display = ("company_name", "status", "price", "currency", "created_at")
    list_filter = ("status",)
    filter_horizontal = ("minerals", "regions")


@admin.register(TermsVersion)
class TermsVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "title", "is_active", "published_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "resource_type", "created_at")
    list_filter = ("action", "resource_type")


admin.site.register(TermsAcceptance)
